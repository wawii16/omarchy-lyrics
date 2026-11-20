import json
import tempfile
import unittest
from pathlib import Path

import backend


class BackendBehavior(unittest.TestCase):
    def test_storefront_defaults_to_local_configuration(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'adam-lyrics' / 'config.json'
            config.parent.mkdir()
            config.write_text('{"storefront": "id"}')
            with patch.dict('os.environ', {'XDG_CONFIG_HOME': directory}, clear=True):
                self.assertEqual(backend.default_storefront(), 'id')

    def test_storefront_environment_override_takes_precedence(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'adam-lyrics' / 'config.json'
            config.parent.mkdir()
            config.write_text('{"storefront": "id"}')
            with patch.dict('os.environ', {'XDG_CONFIG_HOME': directory, 'ADAM_LYRICS_STOREFRONT': 'gb'}, clear=True):
                self.assertEqual(backend.default_storefront(), 'gb')

    def test_invalid_storefront_config_uses_fallback(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'adam-lyrics' / 'config.json'
            config.parent.mkdir()
            config.write_text('{"storefront": "invalid"}')
            with patch.dict('os.environ', {'XDG_CONFIG_HOME': directory}, clear=True):
                self.assertEqual(backend.default_storefront(), 'us')

    def test_published_track_id_distinguishes_same_titles_and_missing_track(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            app = backend.LyricsBackend(path, fetch=lambda _: '<tt><p begin="0">Lyric</p></tt>')
            for track_id in ('123', '456', None):
                state = app.update({'id': track_id, 'title': 'Same', 'position': 1, 'playback': 'Playing'})
                self.assertEqual(state['track_id'], track_id)
                self.assertEqual(json.loads(path.read_text())['track_id'], track_id)

    def test_track_switch_during_fetch_never_publishes_old_lyrics(self):
        with tempfile.TemporaryDirectory() as directory:
            app = backend.LyricsBackend(Path(directory) / 'state.json',
                fetch=lambda _: '<tt><p begin="0">Old lyric</p></tt>',
                refresh_clock=lambda _: {'id': '456', 'title': 'Same', 'position': 1, 'playback': 'Playing'})
            state = app.update({'id': '123', 'title': 'Same', 'position': 1, 'playback': 'Playing'})
            self.assertEqual((state['text'], state['track_id'], state['unavailable']), ('', '456', True))
            self.assertEqual(app.track_id, '456')

    def test_timed_state_follows_seek_and_pause(self):
        ttml = '''<tt xmlns="http://www.w3.org/ns/ttml"><body><div>
          <p begin="00:01.000" end="00:03.000">First</p>
          <p begin="00:03.000" end="00:05.000">Second</p>
        </div></body></tt>'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            app = backend.LyricsBackend(path, fetch=lambda track: ttml)
            app.update({'id': '123', 'title': 'Song', 'playback': 'Playing', 'position': 1.5})
            self.assertEqual(json.loads(path.read_text())['text'], 'First')
            app.update({'id': '123', 'title': 'Song', 'playback': 'Playing', 'position': 3.2})
            self.assertEqual(json.loads(path.read_text())['text'], 'Second')
            app.update({'id': '123', 'title': 'Song', 'playback': 'Paused', 'position': 1.5})
            state = json.loads(path.read_text())
            self.assertEqual((state['text'], state['playback'], state['track'], state['unavailable']), ('First', 'Paused', 'Song', False))
            self.assertIsInstance(state['updated'], float)


    def test_async_incomplete_read_completes_without_leaking_exception(self):
        import contextlib
        import http.client
        import io
        def fetch(_):
            raise http.client.IncompleteRead(b'secret-token', 10)
        with tempfile.TemporaryDirectory() as directory:
            app = backend.LyricsBackend(Path(directory) / 'state.json', fetch, asynchronous=True)
            app.track_id, app.generation, app.fetching = '123', 1, True
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                app.fetch_async('123', 1)
            state = app.update({'id': '123', 'playback': 'Playing', 'position': 0})
            self.assertTrue(state['unavailable'])
            self.assertFalse(app.fetching)
            self.assertEqual(stderr.getvalue(), '')

    def test_async_fetch_does_not_swallow_process_termination(self):
        def fetch(_):
            raise SystemExit(7)
        with tempfile.TemporaryDirectory() as directory:
            app = backend.LyricsBackend(Path(directory) / 'state.json', fetch, asynchronous=True)
            with self.assertRaises(SystemExit):
                app.fetch_async('123', 1)

    def test_async_retry_preserves_unavailable_until_success_or_track_change(self):
        from unittest.mock import patch
        docs = {'123': '<tt/>', '456': '<tt/>'}
        with tempfile.TemporaryDirectory() as directory, patch('backend.threading.Thread'):
            app = backend.LyricsBackend(Path(directory) / 'state.json', lambda track: docs[track], asynchronous=True)
            old = {'id': '123', 'playback': 'Playing', 'position': 0}
            new = {'id': '456', 'playback': 'Playing', 'position': 0}
            self.assertFalse(app.update(old)['unavailable'])  # Initial fetch.
            app.fetch_async('123', app.generation)
            self.assertTrue(app.update(old)['unavailable'])
            for _ in range(2):
                app.retry_at = 0
                self.assertTrue(app.update(old)['unavailable'])  # Retry pending.
                app.fetch_async('123', app.generation)
                self.assertTrue(app.update(old)['unavailable'])
            self.assertFalse(app.update(new)['unavailable'])  # New track loading.
            app.fetch_async('456', app.generation)
            self.assertTrue(app.update(new)['unavailable'])
            app.retry_at = 0
            self.assertTrue(app.update(new)['unavailable'])
            docs['456'] = '<tt><p begin="0">Success</p></tt>'
            app.fetch_async('456', app.generation)
            state = app.update(new)
            self.assertEqual((state['unavailable'], state['text']), (False, 'Success'))

    def test_async_fetch_does_not_block_and_discards_late_track_result(self):
        import threading
        import time
        started, release, completed = threading.Event(), threading.Event(), threading.Event()
        def fetch(track):
            if track == '123':
                started.set()
                release.wait(2)
                completed.set()
                return '<tt><p begin="0">Old</p></tt>'
            return '<tt><p begin="0">New</p><p begin="2">Next</p></tt>'
        with tempfile.TemporaryDirectory() as directory:
            app = backend.LyricsBackend(Path(directory) / 'state.json', fetch=fetch, asynchronous=True)
            old = {'id': '123', 'title': 'Old', 'position': 1, 'playback': 'Playing'}
            new = {'id': '456', 'title': 'New', 'position': 1, 'playback': 'Playing'}
            try:
                state = app.update(old)
                self.assertTrue(started.wait(1))
                self.assertFalse(state['unavailable'])
                app.update(new)
                deadline = time.monotonic() + 1
                while time.monotonic() < deadline:
                    state = app.update(new)
                    if state['text'] == 'New':
                        break
                    time.sleep(.01)
                self.assertEqual((state['track_id'], state['text'], state['next_text']), ('456', 'New', 'Next'))
                release.set()
                self.assertTrue(completed.wait(1))
                time.sleep(.02)
                state = app.update(new)
                self.assertEqual((state['track_id'], state['text'], state['next_text']), ('456', 'New', 'Next'))
            finally:
                release.set()

    def test_instrumental_gap_holds_current_and_next(self):
        with tempfile.TemporaryDirectory() as directory:
            app = backend.LyricsBackend(Path(directory) / 'state.json',
                fetch=lambda _: '<tt><p begin="1" end="2">First</p><p begin="3" end="3.5"> </p><p begin="4" end="5">Second</p></tt>')
            state = app.update({'id': '123', 'position': 3, 'playback': 'Playing'})
            self.assertEqual((state['text'], state['next_text']), ('First', 'Second'))

    def test_known_song_end_stops_at_actual_duration_not_lyric_offset(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {'XDG_CONFIG_HOME': directory}):
            timing = Path(directory) / 'adam-lyrics' / 'timing.json'
            timing.parent.mkdir()
            timing.write_text('{"advance_ms": 1000}')
            app = backend.LyricsBackend(Path(directory) / 'state.json',
                fetch=lambda _: '<tt><p begin="1" end="2">First</p></tt>')
            snapshot = {'id': '123', 'position': 9.5, 'duration': 10, 'playback': 'Playing'}
            state = app.update(snapshot)
            self.assertEqual((state['text'], state['playback']), ('First', 'Playing'))
            snapshot['position'] = 10
            state = app.update(snapshot)
            self.assertEqual((state['text'], state['next_text'], state['playback']), ('', '', 'Stopped'))
            snapshot['duration'] = 0
            state = app.update(snapshot)
            self.assertEqual((state['text'], state['playback']), ('First', 'Playing'))

    def test_current_and_next_follow_playback_seek_gaps_and_track_switch(self):
        docs = {'123': '<tt><p begin="1" end="2">First</p><p begin="3" end="4">Second</p></tt>',
                '456': '<tt><p begin="0" end="5">Other</p></tt>'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            app = backend.LyricsBackend(path, fetch=docs.get)
            snapshot = {'id': '123', 'title': 'Song', 'playback': 'Playing', 'position': 0}
            for position, expected in [(0, ('', 'First')), (1, ('First', 'Second')),
                                       (2, ('First', 'Second')), (3, ('Second', '')),
                                       (4, ('Second', '')), (1.5, ('First', 'Second'))]:
                snapshot['position'] = position
                state = app.update(snapshot)
                self.assertEqual((state['text'], state['next_text']), expected)
                self.assertEqual(json.loads(path.read_text())['next_text'], expected[1])
            snapshot['position'] = 0
            state = app.update(snapshot)
            self.assertEqual((state['text'], state['next_text']), ('', 'First'))
            snapshot.update(id='456', position=1)
            state = app.update(snapshot)
            self.assertEqual((state['text'], state['next_text']), ('Other', ''))
            snapshot.update(id='123', position=0)
            state = app.update(snapshot)
            self.assertEqual((state['text'], state['next_text']), ('', 'First'))
            snapshot['id'] = None
            state = app.update(snapshot)
            self.assertEqual((state['text'], state['next_text']), ('', ''))

    def test_timing_setting_updates_current_and_next_live_without_mutating_snapshot(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {'XDG_CONFIG_HOME': directory}):
            timing = Path(directory) / 'adam-lyrics' / 'timing.json'
            timing.parent.mkdir()
            app = backend.LyricsBackend(Path(directory) / 'state.json', fetch=lambda _: '<tt><p begin="0">First</p><p begin="3">Second</p><p begin="5">Third</p></tt>')
            snapshot = {'id': '123', 'title': 'Song', 'playback': 'Paused', 'position': 2.5}
            state = app.update(snapshot)
            self.assertEqual((state['text'], state['next_text']), ('First', 'Second'))
            timing.write_text('{"advance_ms": 600}')
            state = app.update(snapshot)
            self.assertEqual((state['text'], state['next_text'], state['playback']), ('Second', 'Third', 'Paused'))
            self.assertEqual(snapshot['position'], 2.5)
            timing.write_text('{"advance_ms": -600}')
            snapshot['position'] = 3.5
            state = app.update(snapshot)
            self.assertEqual((state['text'], state['next_text']), ('First', 'Second'))
            self.assertEqual(snapshot['position'], 3.5)

    def test_invalid_timing_files_default_to_zero(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {'XDG_CONFIG_HOME': directory}):
            timing = Path(directory) / 'adam-lyrics' / 'timing.json'
            timing.parent.mkdir()
            app = backend.LyricsBackend(Path(directory) / 'state.json', fetch=lambda _: '<tt><p begin="0">First</p><p begin="3">Second</p></tt>')
            snapshot = {'id': '123', 'playback': 'Playing', 'position': 2.5}
            for contents in (b'{', b'\xff', b'[]', b'{}', b'{"advance_ms": "600"}',
                             b'{"advance_ms": true}', b'{"advance_ms": 600.0}', b'{"advance_ms": 550}'):
                with self.subTest(contents=contents):
                    timing.write_bytes(contents)
                    state = app.update(snapshot)
                    self.assertEqual((state['text'], state['next_text']), ('First', 'Second'))

    def test_timing_offset_is_clamped_to_two_seconds(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {'XDG_CONFIG_HOME': directory}):
            timing = Path(directory) / 'adam-lyrics' / 'timing.json'
            timing.parent.mkdir()
            app = backend.LyricsBackend(Path(directory) / 'state.json', fetch=lambda _: '<tt><p begin="0">First</p><p begin="3">Second</p><p begin="5">Third</p></tt>')
            snapshot = {'id': '123', 'playback': 'Playing', 'position': 2.5}
            timing.write_text('{"advance_ms": 99900}')
            self.assertEqual(app.update(snapshot)['text'], 'Second')
            snapshot['position'] = 4.5
            timing.write_text('{"advance_ms": -99900}')
            self.assertEqual(app.update(snapshot)['text'], 'First')

    def test_pending_fetch_is_not_reported_as_unavailable(self):
        import threading
        release = threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            def fetch(_):
                release.wait(2)
                return '<tt/>'
            app = backend.LyricsBackend(Path(directory) / 'state.json', fetch, asynchronous=True)
            try:
                state = app.update({'id': '123', 'title': 'Song', 'position': 0, 'playback': 'Playing'})
                self.assertFalse(state['unavailable'])
            finally:
                release.set()

    def test_equal_begin_times_accept_missing_end(self):
        document = '<tt><p begin="1">First</p><p begin="1" end="2">Second</p></tt>'
        self.assertEqual(backend.parse_ttml(document), [(1, None, 'First'), (1, 2, 'Second')])

    def test_ttml_seconds_and_milliseconds_units_are_synchronized(self):
        document = '<tt><body><p begin="1500ms" end="3s">A</p></body></tt>'
        with tempfile.TemporaryDirectory() as directory:
            app = backend.LyricsBackend(Path(directory) / 'state.json', fetch=lambda _: document)
            snapshot = {'id': '123', 'title': 'Song', 'playback': 'Playing', 'position': 2}
            self.assertEqual(backend.parse_ttml(document), [(1.5, 3, 'A')])
            self.assertEqual(app.update(snapshot)['text'], 'A')
            snapshot['position'] = 3
            self.assertEqual(app.update(snapshot)['text'], 'A')

    def test_failed_fetch_produces_unavailable_state_then_retries(self):
        calls = []
        def fetch(track):
            calls.append(track)
            if len(calls) == 1:
                raise OSError('engine unavailable')
            return '<tt><body><p begin="0">Recovered</p></body></tt>'
        with tempfile.TemporaryDirectory() as directory:
            app = backend.LyricsBackend(Path(directory) / 'state.json', fetch=fetch, retry_seconds=0)
            snapshot = {'id': '123', 'title': 'Song', 'playback': 'Playing', 'position': 1}
            self.assertTrue(app.update(snapshot)['unavailable'])
            self.assertEqual(app.update(snapshot)['text'], 'Recovered')

    def test_playing_then_genuinely_stopped_does_not_stick_paused(self):
        detector = backend.PlaybackDetector()
        def sample(pos, now, status):
            return detector.resolve({'id': '123', 'position': pos, 'playback': status}, now)
        self.assertEqual(sample(10, 0, 'Playing'), 'Playing')
        self.assertEqual(sample(10.5, .5, 'Playing'), 'Playing')
        self.assertEqual(sample(0, 1, 'Stopped'), 'Stopped')
        self.assertEqual(sample(0, 5, 'Stopped'), 'Stopped')

    def test_stopped_mpris_is_inferred_playing_only_while_position_advances(self):
        detector = backend.PlaybackDetector()
        def sample(position, now, reported='Stopped', track='123'):
            return detector.resolve({'id': track, 'playback': reported, 'position': position}, now)
        self.assertEqual(sample(10, 0), 'Stopped')
        self.assertEqual(sample(10.5, .5), 'Playing')
        self.assertEqual(sample(10.5, 1), 'Playing')
        self.assertEqual(sample(10.5, 2), 'Paused')
        self.assertEqual(sample(2, 2.5, 'Paused'), 'Paused')
        self.assertEqual(sample(0, 3, track='456'), 'Stopped')

    def test_paused_seek_does_not_look_like_playback(self):
        detector = backend.PlaybackDetector()
        def sample(pos, now):
            return detector.resolve({'id': '123', 'playback': 'Stopped', 'position': pos}, now)
        self.assertEqual(sample(10, 0), 'Stopped')
        self.assertEqual(sample(10.5, .5), 'Playing')
        self.assertEqual(sample(10.5, 2), 'Paused')
        self.assertEqual(sample(100, 2.25), 'Paused')

    def test_coarse_mpris_samples_interpolate_lyric_boundaries(self):
        clock = backend.MprisClock()
        with tempfile.TemporaryDirectory() as directory:
            app = backend.LyricsBackend(Path(directory) / 'state.json',
                fetch=lambda _: '<tt><p begin="0">First</p><p begin="11.25">Second</p></tt>')
            def sample(position, now):
                snapshot = {'id': '123', 'title': 'Song', 'playback': 'Playing', 'position': position}
                snapshot['position'] = clock.resolve(snapshot, now)
                return app.update(snapshot)['text']
            self.assertEqual(sample(10, 0), 'First')
            self.assertEqual(sample(11, 1), 'First')
            self.assertEqual(sample(11, 1.25), 'Second')

    def test_clock_stalled_initial_pause_resume_and_bound(self):
        clock = backend.MprisClock()
        def sample(pos, now, status='Playing', track='123'):
            return clock.resolve({'id': track, 'position': pos, 'playback': status}, now)
        self.assertEqual(sample(10, 0), 10)
        self.assertEqual(sample(10, 5), 10)  # No motion evidence.
        self.assertEqual(sample(11, 6), 11)
        self.assertEqual(sample(11, 6.5), 11.5)
        self.assertEqual(sample(11, 10), 12)  # Frozen playing status is bounded.
        self.assertEqual(sample(11, 11, 'Paused'), 11)
        self.assertEqual(sample(11, 12, 'Paused'), 11)
        self.assertEqual(sample(11, 13), 11)  # Resume requires fresh motion.
        self.assertEqual(sample(11, 14), 11)
        self.assertEqual(sample(12, 15), 12)
        self.assertEqual(sample(12, 15.25), 12.25)

    def test_clock_seeks_track_switch_and_regressions(self):
        clock = backend.MprisClock()
        def sample(pos, now, track='123'):
            return clock.resolve({'id': track, 'position': pos, 'playback': 'Playing'}, now)
        self.assertEqual(sample(10, 0), 10)
        self.assertEqual(sample(11, 1), 11)
        self.assertEqual(sample(11, 1.75), 11.75)
        self.assertEqual(sample(11.5, 2), 11.75)  # Coarse update must not regress.
        self.assertEqual(sample(4, 2.25), 4)  # Backward seek.
        self.assertEqual(sample(4, 2.5), 4)
        self.assertEqual(sample(40, 2.75), 40)  # Forward seek.
        self.assertEqual(sample(40, 3), 40)
        self.assertEqual(sample(2, 3.25, '456'), 2)
        self.assertEqual(sample(2, 4, '456'), 2)
        self.assertEqual(sample(0, 5, None), 0)

    def test_cli_uses_interpolated_mpris_position(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            samples = iter([
                {'id': '123', 'title': 'Song', 'position': 10, 'playback': 'Playing'},
                {'id': '123', 'title': 'Song', 'position': 11, 'playback': 'Playing'},
                {'id': '123', 'title': 'Song', 'position': 11, 'playback': 'Playing'}])
            times = iter([0, 1, 1.25])
            published = []
            class App:
                def __init__(self, *args, **kwargs):
                    pass
                def update(self, snapshot):
                    published.append(snapshot['position'])
                    if len(published) == 3:
                        raise StopIteration
            with patch('sys.argv', ['backend', '--state', str(path)]), \
                    patch('backend.read_mpris', side_effect=lambda: next(samples)), \
                    patch('backend.time.monotonic', side_effect=lambda: next(times)), \
                    patch('backend.time.sleep'), patch('backend.LyricsBackend', App):
                with self.assertRaises(StopIteration):
                    backend.main()
            self.assertEqual(published, [10, 11, 11.25])

    def test_mpris_snapshot_reads_id_position_and_status(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        output = '\n'.join(json.dumps(x) for x in [
            {'data': {'mpris:trackid': {'data': '/com/apple/music/track/123'}, 'xesam:title': {'data': 'Song'}}},
            {'data': 'Stopped'}, {'data': 1500000}])
        with patch('backend.subprocess.run', return_value=SimpleNamespace(stdout=output)):
            self.assertEqual(backend.read_mpris(), {'id': '123', 'title': 'Song', 'playback': 'Stopped', 'position': 1.5})

    def test_vlc_clock_rejects_different_duration_and_falls_back_on_failure(self):
        from unittest.mock import patch
        from io import BytesIO
        snapshot = {'id': '123', 'duration': 218.293, 'position': 27.25, 'playback': 'Playing'}
        for response in (BytesIO(b'{"posMs":121750,"lengthMs":190000,"state":"playing"}'), OSError('offline')):
            with self.subTest(response=response), patch('backend.urllib.request.urlopen', side_effect=[response] if isinstance(response, OSError) else None, return_value=response):
                self.assertEqual(backend.apply_vlc_clock(snapshot.copy(), 'http://127.0.0.1:1234', True), snapshot)

    def test_vlc_clock_does_not_trust_duration_alone(self):
        from unittest.mock import patch
        from io import BytesIO
        snapshot = {'id': '123', 'duration': 218.293, 'position': 27.25, 'playback': 'Playing'}
        with patch('backend.urllib.request.urlopen', return_value=BytesIO(b'{"posMs":5000,"lengthMs":218293,"state":"playing"}')):
            self.assertEqual(backend.apply_vlc_clock(snapshot.copy(), 'http://localhost'), snapshot)

    def test_vlc_clock_respects_paused_and_seeks(self):
        from unittest.mock import patch
        from io import BytesIO
        snapshot = {'id': '123', 'duration': 218.293, 'position': 27.25, 'playback': 'Playing'}
        with patch('backend.urllib.request.urlopen', return_value=BytesIO(b'{"posMs":5000,"lengthMs":218293,"state":"paused"}')):
            result = backend.apply_vlc_clock(snapshot, 'http://127.0.0.1:1234', True)
        self.assertEqual((result['position'], result['playback']), (5, 'Paused'))

    def test_cli_rereads_mpris_after_fetch_and_discards_old_track(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            snapshots = [{'id': '123', 'title': 'Same', 'position': 0, 'playback': 'Playing'},
                         {'id': '456', 'title': 'Same', 'position': 1, 'playback': 'Playing'}]
            with patch('sys.argv', ['backend', '--once', '--state', str(path)]), \
                    patch('backend.read_mpris', side_effect=snapshots) as read, \
                    patch('backend.fetch_lyrics', return_value='<tt><p begin="0">Old</p></tt>'):
                backend.main()
            self.assertEqual(read.call_count, 2)
            state = json.loads(path.read_text())
            self.assertEqual((state['track_id'], state['text'], state['unavailable']), ('456', '', True))

    def test_cli_publishes_state_from_mpris_and_engine(self):
        import http.server
        import os
        import subprocess
        import sys
        import threading
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                if self.path == '/api/v1/vlc/time':
                    position = 150000 if getattr(self.server, 'lyrics_fetched', False) else 121750
                    self.wfile.write(json.dumps({'posMs': position, 'lengthMs': 218293, 'state': 'playing'}).encode())
                else:
                    self.server.lyrics_fetched = True
                    self.wfile.write(b'<tt><body><p begin="0" end="100">Stale line</p><p begin="120" end="149">Old sample</p><p begin="149">Live line</p></body></tt>')
            def log_message(self, *args):
                pass
        server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                bindir = Path(directory)
                busctl = bindir / 'busctl'
                output = '\n'.join(json.dumps(x) for x in [
                    {'data': {'mpris:trackid': {'data': '/com/apple/music/track/123'}, 'xesam:title': {'data': 'Song'}, 'mpris:length': {'data': 218293000}}},
                    {'data': 'Stopped'}, {'data': 27250000}])
                busctl.write_text('#!' + sys.executable + '\nprint(' + repr(output) + ')\n')
                busctl.chmod(0o755)
                state = bindir / 'state.json'
                subprocess.run([sys.executable, backend.__file__, '--once', '--state', str(state), '--engine',
                                'http://127.0.0.1:%d' % server.server_port, '--storefront', 'gb', '--unsafe-vlc-clock'],
                               env={**os.environ, 'PATH': str(bindir) + os.pathsep + os.environ['PATH']},
                               check=True, timeout=5)
                result = json.loads(state.read_text())
                self.assertEqual((result['text'], result['playback'], result['track'], result['unavailable']),
                                 ('Live line', 'Playing', 'Song', False))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_engine_request_uses_storefront_and_returns_ttml(self):
        import http.server
        import threading
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.server.request_path = self.path
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'<tt/>')
            def log_message(self, *args):
                pass
        server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = 'http://127.0.0.1:%d' % server.server_port
            self.assertEqual(backend.fetch_lyrics('123', 'gb', url), '<tt/>')
            self.assertEqual(server.request_path, '/api/v1/lyrics/123?sf=gb&format=ttml&type=lyrics')
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
