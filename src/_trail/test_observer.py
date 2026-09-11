import asyncio
import tempfile
import unittest
from pathlib import Path

from trail import Trail


async def wait_until(predicate, timeout: float = 3.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.02)


class FilesObserverTests(unittest.IsolatedAsyncioTestCase):
    async def test_observes_files_in_unrelated_directories(self) -> None:
        with (
            tempfile.TemporaryDirectory() as first_dir,
            tempfile.TemporaryDirectory() as second_dir,
        ):
            first_path = Path(first_dir, "first.txt")
            second_path = Path(second_dir, "second.txt")
            first_path.write_text("first", encoding="utf-8")
            second_path.write_text("second", encoding="utf-8")

            trail = Trail()
            first, second = trail.add(first_path, second_path)
            first_id = first.id
            second_id = second.id

            async with trail.files.observing(debounce=0.05):
                first_path.write_text("changed first", encoding="utf-8")
                second_path.write_text("changed second", encoding="utf-8")
                await wait_until(lambda: first.events and second.events)

            self.assertEqual(first.id, first_id)
            self.assertEqual(second.id, second_id)
            self.assertEqual(first.revision, 1)
            self.assertEqual(second.revision, 1)
            self.assertEqual(first.events[-1].file_id, first.id)
            self.assertEqual(second.events[-1].file_id, second.id)
            self.assertNotEqual(first.events[-1].id, second.events[-1].id)

    async def test_rename_preserves_file_id_and_appends_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "source.txt")
            destination = Path(directory, "destination.txt")
            source.write_text("content", encoding="utf-8")

            trail = Trail()
            (file,) = trail.add(source)
            stable_id = file.id

            async with trail.files.observing(debounce=0.05):
                source.rename(destination)
                await wait_until(lambda: bool(file.events))

            self.assertEqual(file.id, stable_id)
            self.assertEqual(file.revision, 1)
            self.assertEqual(file.events[-1].kind, "moved")
            self.assertEqual(file.path, str(destination.resolve()))

    async def test_deletion_changes_revision_not_file_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "delete-me.txt")
            path.write_text("content", encoding="utf-8")
            trail = Trail()
            (file,) = trail.add(path)
            stable_id = file.id

            async with trail.files.observing(debounce=0.05):
                path.unlink()
                await wait_until(lambda: bool(file.events))

            self.assertEqual(file.id, stable_id)
            self.assertEqual(file.revision, 1)
            self.assertFalse(file.exists)
            self.assertEqual(file.events[-1].kind, "deleted")

    async def test_file_added_while_observing_is_scheduled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "added-later.txt")
            path.write_text("initial", encoding="utf-8")
            trail = Trail()

            async with trail.files.observing(debounce=0.05):
                (file,) = trail.add(path)
                path.write_text("changed", encoding="utf-8")
                await wait_until(lambda: bool(file.events))

            self.assertEqual(file.revision, 1)
            self.assertEqual(file.events[-1].kind, "modified")

    async def test_each_logical_change_gets_a_new_event_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "revisions.txt")
            path.write_text("zero", encoding="utf-8")
            trail = Trail()
            (file,) = trail.add(path)

            async with trail.files.observing(debounce=0.05):
                path.write_text("one", encoding="utf-8")
                await wait_until(lambda: len(file.events) == 1)
                first_event_id = file.events[-1].id

                path.write_text("two", encoding="utf-8")
                await wait_until(lambda: len(file.events) == 2)

            self.assertEqual(file.revision, 2)
            self.assertNotEqual(first_event_id, file.events[-1].id)


if __name__ == "__main__":
    unittest.main()
