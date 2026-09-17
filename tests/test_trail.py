from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from trail import Trail
from trail.entry import Entry
from trail.event import AddEntryEvent, RemoveEntryEvent, WatchdogEvent


class TestTrail:
    @staticmethod
    @contextmanager
    def workspace() -> Iterator[Path]:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            csv = root / 'dataset.csv'
            csv.write_text('name,value\nexample,42\n', encoding='utf-8')
            yield root

    @staticmethod
    def opened_event(
            trail: Trail,
            csv: Path,
            previous: set[int],
    ) -> WatchdogEvent | None:
        return next(
            (
                event
                for event in trail.events.values()
                if event.id not in previous
                and isinstance(event, WatchdogEvent)
                and event.event_type == 'opened'
                and event.src_path == str(csv)
            ),
            None,
        )

    def test_pathless_add_and_open(self) -> None:
        async def run() -> None:
            with self.workspace() as root:
                csv = root / 'dataset.csv'
                trail = Trail()
                entry = trail.add(csv)[0]
                addition = next(iter(trail.events.values()))
                assert isinstance(addition, AddEntryEvent)
                assert addition.entry is entry
                async with trail.watchdog.context():
                    assert trail.watchdog.observer.is_alive()
                    previous = set(trail.events)
                    with csv.open(encoding='utf-8') as stream:
                        assert stream.read() == 'name,value\nexample,42\n'
                    async with asyncio.timeout(5):
                        while (
                            opened := self.opened_event(trail, csv, previous)
                        ) is None:
                            await asyncio.sleep(0.01)
                assert opened.entry is entry
                assert trail.dir is None
                assert trail.events.jsonl.path is None
                assert list(root.iterdir()) == [csv]

        asyncio.run(run())

    def test_persistent_add_open_and_new_session(self) -> None:
        async def run() -> None:
            with self.workspace() as root:
                csv = root / 'dataset.csv'
                trail = Trail(root)
                entry = trail.add(csv)[0]
                async with trail.watchdog.context():
                    previous = set(trail.events)
                    with csv.open(encoding='utf-8') as stream:
                        assert stream.read() == 'name,value\nexample,42\n'
                    async with asyncio.timeout(5):
                        while (
                            opened := self.opened_event(trail, csv, previous)
                        ) is None:
                            await asyncio.sleep(0.01)
                assert opened.entry is entry
                records = [
                    event.to_record()
                    for event in trail.events.values()
                ]
                stored = [
                    json.loads(line)
                    for line in trail.events.jsonl.path.read_text(
                        encoding='utf-8'
                    ).splitlines()
                ]
                assert stored == records
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    '-c',
                    'import json, sys; from trail import Trail; '
                    'trail = Trail(sys.argv[1]); '
                    'print(json.dumps({"id": trail.id, '
                    '"events": [event.to_record() for event in trail.events.values()], '
                    '"entry_id": trail.entries[sys.argv[2]].id}))',
                    str(root),
                    str(csv),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=5,
                )
                assert process.returncode == 0, stderr.decode()
                snapshot = json.loads(stdout)
                assert snapshot['id'] == trail.id
                assert snapshot['events'] == records
                assert snapshot['entry_id'] == entry.id
                restored = Trail(root)
                assert restored.id == trail.id
                assert [
                    event.to_record()
                    for event in restored.events.values()
                ] == records
                restored_entry = restored.entries[csv]
                assert restored_entry.id == entry.id
                assert all(
                    event.entry is restored_entry
                    for event in restored.events.values()
                )
                async with restored.watchdog.context():
                    previous = set(restored.events)
                    with csv.open(encoding='utf-8') as stream:
                        assert stream.read() == 'name,value\nexample,42\n'
                    async with asyncio.timeout(5):
                        while (
                            reopened := self.opened_event(restored, csv, previous)
                        ) is None:
                            await asyncio.sleep(0.01)
                assert reopened.entry is restored_entry
                previous_ids = {
                    record['id']
                    for record in records
                }
                assert reopened.id not in previous_ids
                third = Trail(root)
                assert reopened.id in third.events

        asyncio.run(run())

    def test_removed_file_stays_untracked_after_new_session(self) -> None:
        with self.workspace() as root:
            csv = root / 'dataset.csv'
            trail = Trail(root)
            entry = trail.add(csv)[0]
            trail.remove(csv)
            restored = Trail(root)
            assert csv not in restored.entries
            removal = list(restored.events.values())[-1]
            assert isinstance(removal, RemoveEntryEvent)
            assert removal.entry.id == entry.id
            opened = WatchdogEvent(src_path=str(csv), event_type='opened')
            assert opened.apply(restored) is None
            assert opened.id not in restored.events
            assert len(restored.events) == 2

    def test_replay_dispatches_to_event_subclass(self) -> None:
        replayed = []

        class CustomAddEvent(AddEntryEvent):
            def apply(
                    self,
                    trail: Trail,
                    *,
                    replay: bool = False,
            ) -> Entry:
                entry = AddEntryEvent.apply(self, trail, replay=replay)
                if replay:
                    replayed.append(self.id)
                return entry

        with self.workspace() as root:
            csv = root / 'dataset.csv'
            trail = Trail(root)
            event = CustomAddEvent(src_path=str(csv))
            entry = event.apply(trail)
            trail.events[event.id] = event
            history = trail.events.jsonl.path.read_bytes()
            csv.unlink()

            restored = Trail(root)

            assert replayed == [event.id]
            assert restored.entries[csv].id == entry.id
            assert isinstance(restored.events[event.id], CustomAddEvent)
            assert restored.events.jsonl.path.read_bytes() == history

    def test_deleted_csv_history_can_be_restored(self) -> None:
        async def run() -> None:
            with self.workspace() as root:
                csv = root / 'dataset.csv'
                trail = Trail(root)
                entry = trail.add(csv)[0]
                async with trail.watchdog.context():
                    previous = set(trail.events)
                    with csv.open(encoding='utf-8') as stream:
                        assert stream.read() == 'name,value\nexample,42\n'
                    async with asyncio.timeout(5):
                        while (
                            self.opened_event(trail, csv, previous) is None
                        ):
                            await asyncio.sleep(0.01)
                records = [
                    event.to_record()
                    for event in trail.events.values()
                ]
                csv.unlink()
                restored = Trail(root)
                assert restored.entries[csv].id == entry.id
                assert [
                    event.to_record()
                    for event in restored.events.values()
                ] == records

        asyncio.run(run())


if __name__ == '__main__':
    if sys.platform != 'linux':
        raise SystemExit('file opening requires Linux inotify')

    test_object = TestTrail()
    tests = [
        ('test_pathless_add_and_open', 'pathless trail tracks an opened CSV'),
        (
            'test_persistent_add_open_and_new_session',
            'persistent trail survives new sessions',
        ),
        (
            'test_removed_file_stays_untracked_after_new_session',
            'removed files remain untracked',
        ),
        (
            'test_deleted_csv_history_can_be_restored',
            'deleted CSV history is restored',
        ),
        (
            'test_replay_dispatches_to_event_subclass',
            'event subclasses control their own replay',
        ),
    ]

    for method_name, description in tests:
        getattr(test_object, method_name)()
        print(f'  ✓ {description}')
