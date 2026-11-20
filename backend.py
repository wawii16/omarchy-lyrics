#!/usr/bin/env python3
"""Publish Adam's current lyric to a small JSON state file."""
import json
import os
import queue
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
import ssl
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path


def default_storefront():
    """Use the explicit environment override, then the local user config."""
    override = os.environ.get('ADAM_LYRICS_STOREFRONT')
    if override:
        return override
    config_dir = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    try:
        value = json.loads((config_dir / 'adam-lyrics' / 'config.json').read_text(encoding='utf-8')).get('storefront')
        if isinstance(value, str) and len(value) == 2 and value.isascii() and value.isalpha():
            return value.lower()
    except (OSError, ValueError, AttributeError):
        pass
    return 'us'


def fetch_lyrics(track_id, storefront, engine='https://127.0.0.1:20025'):
    query = urllib.parse.urlencode({'sf': storefront, 'format': 'ttml', 'type': 'lyrics'})
    url = engine.rstrip('/') + '/api/v1/lyrics/' + urllib.parse.quote(str(track_id), safe='') + '?' + query
    context = ssl._create_unverified_context() if engine.startswith('https://127.0.0.1:') else None
    with urllib.request.urlopen(url, timeout=5, context=context) as response:
        return response.read().decode('utf-8')


def read_mpris():
    result = subprocess.run(['busctl', '--user', '--json=short', 'get-property',
        'org.mpris.MediaPlayer2.adam', '/org/mpris/MediaPlayer2',
        'org.mpris.MediaPlayer2.Player', 'Metadata', 'PlaybackStatus', 'Position'],
        capture_output=True, text=True, check=True, timeout=2)
    metadata, status, position = (json.loads(line)['data'] for line in result.stdout.splitlines())
    track_path = metadata.get('mpris:trackid', {}).get('data', '')
    track_id = track_path.rsplit('/', 1)[-1]
    if not track_id.isdecimal():
        track_id = None
    snapshot = {'id': track_id, 'title': metadata.get('xesam:title', {}).get('data', ''),
                'playback': status, 'position': position / 1000000}
    if 'mpris:length' in metadata:
        snapshot['duration'] = metadata['mpris:length']['data'] / 1000000
    return snapshot


def apply_vlc_clock(snapshot, engine, allow_unverified=False):
    """Use duration-only VLC timing only with explicit, unsafe opt-in."""
    if not allow_unverified or not snapshot.get('id') or not snapshot.get('duration'):
        return snapshot
    try:
        context = ssl._create_unverified_context() if engine.startswith('https://127.0.0.1:') else None
        with urllib.request.urlopen(engine.rstrip('/') + '/api/v1/vlc/time', timeout=0.3, context=context) as response:
            vlc = json.load(response)
        position, length, state = vlc['posMs'], vlc['lengthMs'], vlc['state']
        if (state in ('playing', 'paused') and isinstance(position, (int, float))
                and isinstance(length, (int, float)) and position >= 0 and length > 0
                and abs(length / 1000 - snapshot['duration']) <= 1):
            snapshot['position'] = position / 1000
            snapshot['playback'] = 'Playing' if state == 'playing' else 'Paused'
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return snapshot


def timestamp(value):
    if value.endswith('ms'):
        return float(value[:-2]) / 1000
    if value.endswith('s'):
        return float(value[:-1])
    parts = value.split(':')
    return sum(float(part) * 60 ** n for n, part in enumerate(reversed(parts)))


def parse_ttml(document):
    root = ET.fromstring(document)
    lines = []
    for node in root.iter():
        if node.tag.rsplit('}', 1)[-1] != 'p' or 'begin' not in node.attrib:
            continue
        text = ''.join(node.itertext()).strip()
        if text:
            lines.append((timestamp(node.attrib['begin']), timestamp(node.attrib['end']) if 'end' in node.attrib else None, text))
    return sorted(lines, key=lambda line: line[0])


class PlaybackDetector:
    """Compensate for Adam versions that report Stopped while advancing."""
    def __init__(self):
        self.track = None
        self.position = None
        self.sample_at = None
        self.last_advance = None
        self.seen_playing = False

    def resolve(self, snapshot, now):
        track, position = snapshot.get('id'), snapshot.get('position', 0)
        reported = snapshot.get('playback', 'Stopped')
        if track != self.track:
            self.track, self.position, self.last_advance, self.seen_playing = track, None, None, False
        if reported == 'Stopped' and self.position is not None and self.sample_at is not None:
            delta = position - self.position
            elapsed = max(0, now - self.sample_at)
            if 0.02 < delta <= max(1.25, elapsed * 1.75):
                self.last_advance, self.seen_playing = now, True
        self.position, self.sample_at = position, now
        if reported in ('Playing', 'Paused'):
            self.last_advance, self.seen_playing = None, False
            return reported
        # Once Adam has reported Stopped while its position advanced, a later
        # stationary Stopped cannot distinguish a pause from a genuine stop.
        if self.last_advance is not None and now - self.last_advance < 1.25:
            return 'Playing'
        return 'Paused' if self.seen_playing and track else 'Stopped'


class MprisClock:
    """Interpolate coarse MPRIS positions only after observing movement.

    Position is never extrapolated more than one second past the latest
    observed advance; a frozen or misreported player cannot drift forever.
    """
    MAX_EXTRAPOLATION = 1.0

    def __init__(self):
        self.track = None
        self.raw = None
        self.anchor_at = None
        self.output = None
        self.active = False

    def resolve(self, snapshot, now):
        track = snapshot.get('id')
        position = snapshot.get('position', 0)
        playing = snapshot.get('playback') == 'Playing' and bool(track)
        if (track != self.track or self.raw is None or not playing
                or not self.active or now < self.anchor_at):
            self.track, self.raw, self.anchor_at = track, position, now
            self.output, self.active = position, playing
            self.moving = False
            return position
        if position != self.raw:
            elapsed = now - self.anchor_at
            delta = position - self.raw
            # Large forward jumps and every backwards jump are seeks.
            seek = delta < 0 or delta > elapsed + self.MAX_EXTRAPOLATION
            self.output = position if seek else max(position, self.output)
            self.raw, self.anchor_at = position, now
            self.moving = not seek
        elif self.moving:
            estimate = position + min(max(0, now - self.anchor_at), self.MAX_EXTRAPOLATION)
            self.output = max(self.output, estimate)
        return self.output


class LyricsBackend:
    def __init__(self, path, fetch, retry_seconds=30, refresh_clock=None, asynchronous=False):
        self.path = Path(path)
        self.fetch = fetch
        self.refresh_clock = refresh_clock
        self.retry_seconds = retry_seconds
        self.retry_at = 0
        self.track_id = None
        self.lines = []
        self.asynchronous = asynchronous
        self.results = queue.SimpleQueue()
        self.generation = 0
        self.fetching = False
        self.fetch_completed = False

    def fetch_async(self, track_id, generation):
        try:
            lines = parse_ttml(self.fetch(track_id))
        except Exception:
            # Fetch/parsing failures must complete the request without logging
            # exception details, which may contain response data or credentials.
            lines = []
        self.results.put((generation, lines))

    def update(self, snapshot):
        track_id = snapshot.get('id')
        if track_id != self.track_id:
            self.track_id = track_id
            self.lines = []
            self.retry_at = 0
            self.generation += 1
            self.fetching = False
            self.fetch_completed = False
        if self.asynchronous:
            while not self.results.empty():
                generation, lines = self.results.get_nowait()
                if generation == self.generation:
                    self.lines = lines
                    self.fetching = False
                    self.fetch_completed = True
                    self.retry_at = time.monotonic() + self.retry_seconds
            if track_id and not self.lines and not self.fetching and time.monotonic() >= self.retry_at:
                self.fetching = True
                threading.Thread(target=self.fetch_async, args=(track_id, self.generation), daemon=True).start()
        elif track_id and not self.lines and time.monotonic() >= self.retry_at:
            try:
                self.lines = parse_ttml(self.fetch(track_id))
            except Exception:
                # Match async fetch handling without logging response data.
                self.lines = []
            self.retry_at = time.monotonic() + self.retry_seconds
            # Fetching lyrics can take seconds; do not publish the pre-fetch clock.
            if self.refresh_clock:
                snapshot = self.refresh_clock(snapshot)
                if snapshot.get('id') != track_id:
                    self.track_id = snapshot.get('id')
                    self.lines = []
                    self.retry_at = 0
        config_dir = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
        try:
            advance_ms = json.loads((config_dir / 'adam-lyrics' / 'timing.json').read_text(encoding='utf-8'))['advance_ms']
        except (OSError, ValueError, KeyError, TypeError):
            advance_ms = 0
        if type(advance_ms) is not int or advance_ms % 100:
            advance_ms = 0
        advance_ms = max(-2000, min(2000, advance_ms))
        position = snapshot.get('position', 0) + advance_ms / 1000
        current = ''
        next_text = ''
        for begin, _end, text in self.lines:
            if begin > position:
                next_text = text
                break
            current = text
        playback = snapshot.get('playback', 'Stopped')
        duration = snapshot.get('duration')
        # The lyric offset changes highlighting, not the actual track boundary.
        if isinstance(duration, (int, float)) and duration > 0 and snapshot.get('position', 0) >= duration:
            current, next_text, playback = '', '', 'Stopped'
        state = {'text': current, 'next_text': next_text, 'playback': playback, 'unavailable': (not self.fetching or self.fetch_completed) and not bool(self.lines), 'track': snapshot.get('title', ''), 'track_id': snapshot.get('id'), 'updated': time.time()}
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(dir=self.path.parent, prefix='.state-', suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(state, stream, ensure_ascii=False)
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        return state


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', default=f'/tmp/adam-lyrics-{os.getuid()}/state.json')
    parser.add_argument('--storefront', default=default_storefront(),
                        help='Apple Music storefront (flag, environment, user config, then us)')
    parser.add_argument('--engine', default='https://127.0.0.1:20025')
    parser.add_argument('--unsafe-vlc-clock', action='store_true',
                        help='use VLC duration-only clock matching; may sync to the wrong track')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    detector = PlaybackDetector()
    clock = MprisClock()
    if not args.unsafe_vlc_clock:
        print('VLC clock disabled: track identity cannot be verified; MPRIS may lag or freeze. '
              'Use --unsafe-vlc-clock to opt in to duration-only matching.', file=sys.stderr)

    def current_snapshot():
        try:
            snapshot = read_mpris()
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
            snapshot = {'id': None, 'title': '', 'playback': 'Stopped', 'position': 0}
        now = time.monotonic()
        snapshot['playback'] = detector.resolve(snapshot, now)
        snapshot['position'] = clock.resolve(snapshot, now)
        return apply_vlc_clock(snapshot, args.engine, args.unsafe_vlc_clock)

    app = LyricsBackend(args.state, lambda track: fetch_lyrics(track, args.storefront, args.engine),
                        refresh_clock=lambda _: current_snapshot(), asynchronous=not args.once)
    while True:
        app.update(current_snapshot())
        if args.once:
            break
        time.sleep(0.25)


if __name__ == '__main__':
    main()
