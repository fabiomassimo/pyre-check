# Copyright (c) 2016-present, Facebook, Inc.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List
from unittest.mock import MagicMock, call, patch

from .. import buck, filesystem
from ..analysis_directory import (
    AnalysisDirectory,
    SharedAnalysisDirectory,
    UpdatedPaths,
    resolve_analysis_directory,
)


class AnalysisDirectoryTest(unittest.TestCase):
    def assertEqualRootAndFilterRoot(
        self, actual: AnalysisDirectory, expected: AnalysisDirectory
    ) -> None:
        self.assertEqual(expected.get_root(), actual.get_root())
        self.assertEqual(expected.get_filter_root(), actual.get_filter_root())

    @patch.object(os.path, "isfile")
    @patch.object(os.path, "abspath", side_effect=lambda path: path)
    def test_process_updated_files(self, abspath: MagicMock, isfile: MagicMock) -> None:
        analysis_directory = AnalysisDirectory(
            path="foo/bar", search_path=["baz$hello"]
        )
        isfile.side_effect = lambda path: path != "foo/bar/deleted.py"
        actual = analysis_directory.process_updated_files(
            [
                "foo/bar/tracked.py",
                "foo/not_tracked.py",
                "baz/hello/also_tracked.py",
                "foo/bar/deleted.py",
            ]
        )
        expected = UpdatedPaths(
            updated_paths=["foo/bar/tracked.py", "baz/hello/also_tracked.py"],
            deleted_paths=["foo/bar/deleted.py"],
        )
        self.assertEqual(actual, expected)

    @patch.object(
        buck,
        "generate_source_directories",
        side_effect=lambda targets, build, prompt: targets,
    )
    def test_resolve_analysis_directory(self, buck) -> None:  # pyre-fixme[2]
        arguments = MagicMock()
        arguments.build = None
        arguments.original_directory = "/project"
        arguments.current_directory = "/project"

        configuration = MagicMock()
        configuration.source_directories = []
        configuration.targets = []
        configuration.local_configuration_root = None

        arguments.source_directories = ["a/b"]
        arguments.targets = []
        arguments.filter_directory = None
        expected_analysis_directory = AnalysisDirectory("a/b")
        analysis_directory = resolve_analysis_directory(arguments, configuration)
        self.assertEqualRootAndFilterRoot(
            analysis_directory, expected_analysis_directory
        )

        arguments.source_directories = ["/symlinked/directory"]
        arguments.targets = []
        arguments.filter_directory = "/real/directory"
        expected_analysis_directory = AnalysisDirectory(
            "/symlinked/directory", filter_paths=["/real/directory"]
        )
        analysis_directory = resolve_analysis_directory(arguments, configuration)
        self.assertEqualRootAndFilterRoot(
            analysis_directory, expected_analysis_directory
        )


class SharedAnalysisDirectoryTest(unittest.TestCase):
    def assertEqualRootAndFilterRoot(
        self, actual: AnalysisDirectory, expected: AnalysisDirectory
    ) -> None:
        self.assertEqual(expected.get_root(), actual.get_root())
        self.assertEqual(expected.get_filter_root(), actual.get_filter_root())

    def assertFileIsLinkedBothWays(
        self,
        relative_path: str,
        shared_analysis_directory: SharedAnalysisDirectory,
        scratch_directory: str,
        project_directory: str,
    ) -> None:
        self.assertEqual(
            os.path.realpath(os.path.join(scratch_directory, relative_path)),
            os.path.join(project_directory, relative_path),
        )
        self.assertEqual(
            shared_analysis_directory._symbolic_links[
                os.path.join(project_directory, relative_path)
            ],
            os.path.join(scratch_directory, relative_path),
        )

    def test_should_rebuild(self) -> None:
        self.assertTrue(
            SharedAnalysisDirectory.should_rebuild(
                updated_tracked_paths=["a.py", "b.py", "c.py", "d.py"],
                new_paths=[],
                deleted_paths=[],
            )
        )
        self.assertTrue(
            SharedAnalysisDirectory.should_rebuild(
                updated_tracked_paths=[],
                new_paths=["a.py", "b.py"],
                deleted_paths=["c.py", "d.py", "e.py"],
            )
        )
        self.assertFalse(
            SharedAnalysisDirectory.should_rebuild(
                updated_tracked_paths=["a.py"], new_paths=[], deleted_paths=[]
            )
        )

    @patch.object(SharedAnalysisDirectory, "should_rebuild", return_value=False)
    @patch.object(os, "getcwd", return_value="project")
    @patch.object(os.path, "isfile")
    @patch.object(os.path, "abspath", side_effect=lambda path: path)
    def test_process_updated_files_no_rebuild(
        self,
        abspath: MagicMock,
        isfile: MagicMock,
        getcwd: MagicMock,
        should_rebuild: MagicMock,
    ) -> None:
        shared_analysis_directory = SharedAnalysisDirectory(
            source_directories=[], targets=["target1"], search_path=["baz$hello"]
        )
        isfile.side_effect = lambda path: path != "project/deleted.py"

        shared_analysis_directory._symbolic_links = {
            "project/tracked.py": "scratch/bar/tracked.py"
        }
        actual = shared_analysis_directory.process_updated_files(
            [
                "project/tracked.py",
                "other_project/not_tracked.py",
                "project/something/new_file.py",
                "project/deleted.py",
                "baz/hello/new_file_tracked_because_of_search_path.py",
            ]
        )
        # We ignore individually added or deleted paths unless there is a
        # rebuild. Note, however, that new files in the search_path are shown as
        # updated files. This is the existing behavior and may be a bug.
        expected = UpdatedPaths(
            updated_paths=[
                "scratch/bar/tracked.py",
                "baz/hello/new_file_tracked_because_of_search_path.py",
            ],
            deleted_paths=[],
        )
        self.assertEqual(actual, expected)

    @patch.object(SharedAnalysisDirectory, "rebuild")
    @patch.object(SharedAnalysisDirectory, "should_rebuild", return_value=True)
    @patch.object(os, "getcwd", return_value="project")
    @patch.object(os.path, "isfile")
    @patch.object(os.path, "abspath", side_effect=lambda path: path)
    def test_process_updated_files_rebuild(
        self,
        abspath: MagicMock,
        isfile: MagicMock,
        getcwd: MagicMock,
        should_rebuild: MagicMock,
        rebuild: MagicMock,
    ) -> None:
        shared_analysis_directory = SharedAnalysisDirectory(
            source_directories=[], targets=["target1"], search_path=["baz$hello"]
        )
        isfile.side_effect = lambda path: path != "project/deleted.py"

        def update_paths_for_rebuild() -> None:
            shared_analysis_directory._symbolic_links[
                "project/something/new_file_from_rebuild.py"
            ] = "scratch/new_file_from_rebuild.py"
            del shared_analysis_directory._symbolic_links[
                "project/deleted_by_rebuild.py"
            ]

        rebuild.side_effect = update_paths_for_rebuild

        shared_analysis_directory._symbolic_links = {
            "project/tracked.py": "scratch/tracked.py",
            "project/deleted_by_rebuild.py": "scratch/deleted_by_rebuild.py",
        }
        actual = shared_analysis_directory.process_updated_files(
            [
                "project/tracked.py",
                "other_project/not_tracked.py",
                "project/something/new_file.py",
                "project/deleted.py",
                "baz/hello/new_file_tracked_because_of_search_path.py",
            ]
        )
        expected = UpdatedPaths(
            updated_paths=[
                # Tracked files.
                "scratch/tracked.py",
                "baz/hello/new_file_tracked_because_of_search_path.py",
                # New file from the rebuild.
                "scratch/new_file_from_rebuild.py",
            ],
            deleted_paths=["scratch/deleted_by_rebuild.py"],
        )
        self.assertEqual(actual, expected)

    @patch.object(
        buck,
        "generate_source_directories",
        side_effect=lambda targets, build, prompt: targets,
    )
    def test_resolve_analysis_directory(self, buck) -> None:  # pyre-fixme[2]
        arguments = MagicMock()
        arguments.build = None
        arguments.original_directory = "/project"
        arguments.current_directory = "/project"

        configuration = MagicMock()
        configuration.source_directories = []
        configuration.targets = []
        configuration.local_configuration_root = None

        arguments.source_directories = []
        arguments.targets = ["//x:y"]
        arguments.filter_directory = "/real/directory"
        expected_analysis_directory = SharedAnalysisDirectory(
            [],
            ["//x:y"],
            original_directory="/project",
            filter_paths=["/real/directory"],
        )
        analysis_directory = resolve_analysis_directory(arguments, configuration)
        self.assertEqualRootAndFilterRoot(
            analysis_directory, expected_analysis_directory
        )

        arguments.source_directories = ["a/b"]
        arguments.targets = ["//x:y", "//y/..."]
        arguments.filter_directory = "/filter"
        configuration.targets = ["//overridden/..."]
        expected_analysis_directory = SharedAnalysisDirectory(
            ["a/b"],
            ["//x:y", "//y:/..."],
            original_directory="/project",
            filter_paths=["/filter"],
        )
        analysis_directory = resolve_analysis_directory(arguments, configuration)
        self.assertEqualRootAndFilterRoot(
            analysis_directory, expected_analysis_directory
        )

        arguments.source_directories = []
        arguments.targets = []
        arguments.filter_directory = "/filter"
        configuration.source_directories = []
        configuration.targets = ["//not:overridden/..."]
        expected_analysis_directory = SharedAnalysisDirectory(
            [],
            ["//not:overridden/..."],
            original_directory="/project",
            filter_paths=["/filter"],
        )
        analysis_directory = resolve_analysis_directory(arguments, configuration)
        self.assertEqualRootAndFilterRoot(
            analysis_directory, expected_analysis_directory
        )

    def test_merge_into_paths(self) -> None:
        directory = tempfile.mkdtemp()  # type: str
        root = os.path.realpath(directory)

        Path(root, "a.py").touch()
        Path(root, "b.pyi").touch()
        Path(root, "c.cpp").touch()
        Path(root, "link1.py").symlink_to(Path(root, "a.py"))
        Path(root, "link2.py").symlink_to(Path(root, "dangling.py"))
        Path(root, "link3.py").symlink_to(Path(root, "c.cpp"))
        Path(root, "link4.cpp").symlink_to(Path(root, "a.py"))
        os.mkdir(os.path.join(root, "mypy"))
        os.mkdir(os.path.join(root, "scipyi"))
        os.mkdir(os.path.join(root, "spy.py"))
        Path(root, "directory_symlink.py").symlink_to(Path(root, "spy.py"))
        Path(root, "mypy/my.py").touch()
        Path(root, "scipyi/sci.pyi").touch()
        Path(root, "mypy/another.pyi").symlink_to(Path(root, "mypy/my.py"))
        Path(root, "scipyi/another.py").symlink_to(Path(root, "scipyi/sci.pyi"))
        shared_analysis_directory = SharedAnalysisDirectory([root], [])
        all_paths = {}  # type: Dict[str, str]
        shared_analysis_directory._merge_into_paths(root, all_paths)
        self.assertEqual(
            all_paths,
            {
                "a.py": os.path.join(root, "a.py"),
                "b.pyi": os.path.join(root, "b.pyi"),
                "link1.py": os.path.join(root, "a.py"),
                "link3.py": os.path.join(root, "c.cpp"),
                "mypy/another.pyi": os.path.join(root, "mypy/my.py"),
                "mypy/my.py": os.path.join(root, "mypy/my.py"),
                "scipyi/another.py": os.path.join(root, "scipyi/sci.pyi"),
                "scipyi/sci.pyi": os.path.join(root, "scipyi/sci.pyi"),
            },
        )

    @patch.object(filesystem, "is_empty", return_value=False)
    @patch.object(os, "symlink")
    @patch.object(subprocess, "check_output")
    @patch.object(os, "makedirs")
    @patch.object(os.path, "exists")
    @patch.object(os.path, "realpath")
    def test_merge(
        self,
        os_path_realpath: MagicMock,
        os_path_exists: MagicMock,
        os_makedirs: MagicMock,
        check_output: MagicMock,
        os_symlink: MagicMock,
        is_empty: MagicMock,
    ) -> None:
        os_path_exists.return_value = False
        root = tempfile.mkdtemp()
        os.mkdir(os.path.join(root, "first"))
        os.mkdir(os.path.join(root, "first", "b"))
        os.mkdir(os.path.join(root, "second"))

        Path(root, "first", "x.py").touch()
        Path(root, "first", "y.py").touch()
        Path(root, "first", "b", "z.py").touch()
        Path(root, "second", "a.py").touch()

        # pyre-fixme[2]: Parameter `stderr` has type `None` but no type is specified.
        def side_effect(path: str, stderr=None) -> bytes:
            if path[1].endswith("first"):
                serialized = "\n".join(
                    [
                        os.path.join(root, path)
                        for path in ["first/x.py", "first/y.py", "first/b/z.py"]
                    ]
                )
            else:
                serialized = os.path.join(root, "second/a.py")
            return bytes(serialized, "utf-8")

        check_output.side_effect = side_effect
        os_path_realpath.side_effect = lambda x: x
        shared_analysis_directory = SharedAnalysisDirectory(
            [os.path.join(root, "first"), os.path.join(root, "second")], []
        )
        shared_analysis_directory._merge()
        shared_root = shared_analysis_directory.get_root()
        os_makedirs.assert_has_calls(
            [call(shared_root), call(shared_root + "/b")], any_order=True
        )
        os_symlink.assert_has_calls(
            [
                call(root + "/first/x.py", shared_root + "/x.py"),
                call(root + "/first/y.py", shared_root + "/y.py"),
                call(root + "/first/b/z.py", shared_root + "/b/z.py"),
                call(root + "/second/a.py", shared_root + "/a.py"),
            ],
            any_order=True,
        )

    def test_prepare(self) -> None:
        buck_output_directory = tempfile.mkdtemp()  # type: str
        project_directory = tempfile.mkdtemp()  # type: str
        original_scratch_directory = tempfile.mkdtemp()  # type: str

        with patch.object(buck.FastBuckBuilder, "build") as build, patch.object(
            SharedAnalysisDirectory, "get_root", return_value=original_scratch_directory
        ):
            fast_buck_builder = buck.FastBuckBuilder(buck_root="dummy_buck_root")
            shared_analysis_directory = SharedAnalysisDirectory(
                source_directories=[],
                targets=["target1"],
                buck_builder=fast_buck_builder,
            )

            Path(project_directory, "existing.py").touch()

            def build_buck_directory(argument: filesystem.BuckBuilder) -> List[str]:
                Path(buck_output_directory, "existing.py").symlink_to(
                    Path(Path(project_directory, "existing.py"))
                )
                return [buck_output_directory]

            build.side_effect = build_buck_directory

            Path(original_scratch_directory, "obsolete.py").touch()

            shared_analysis_directory.prepare()

            self.assertFalse(
                os.path.lexists(os.path.join(original_scratch_directory, "obsolete.py"))
            )

            self.assertFileIsLinkedBothWays(
                "existing.py",
                shared_analysis_directory,
                original_scratch_directory,
                project_directory,
            )

    def test_rebuild(self) -> None:
        buck_output_directory = tempfile.mkdtemp("_buck_output")  # type: str
        project_directory = tempfile.mkdtemp("_project")  # type: str
        original_scratch_directory = tempfile.mkdtemp("_original_scratch")  # type: str

        with patch.object(buck.FastBuckBuilder, "build") as build, patch.object(
            SharedAnalysisDirectory, "get_root", return_value=original_scratch_directory
        ):
            fast_buck_builder = buck.FastBuckBuilder(buck_root="dummy_buck_root")
            shared_analysis_directory = SharedAnalysisDirectory(
                source_directories=[],
                targets=["target1"],
                buck_builder=fast_buck_builder,
            )

            Path(project_directory, "existing.py").touch()
            Path(project_directory, "to_be_deleted.py").touch()

            def build_buck_directory(argument: filesystem.BuckBuilder) -> List[str]:
                Path(buck_output_directory, "existing.py").symlink_to(
                    Path(project_directory, "existing.py")
                )
                Path(buck_output_directory, "to_be_deleted.py").symlink_to(
                    Path(project_directory, "to_be_deleted.py")
                )
                return [buck_output_directory]

            build.side_effect = build_buck_directory

            Path(
                original_scratch_directory, "obsolete_file_in_scratch_directory.py"
            ).touch()

            shared_analysis_directory.prepare()

            # Update the project directory.
            Path(project_directory, "new_file.py").touch()
            os.remove(os.path.join(project_directory, "to_be_deleted.py"))

            def update_buck_directory() -> None:
                os.remove(os.path.join(buck_output_directory, "to_be_deleted.py"))
                Path(buck_output_directory, "new_file.py").symlink_to(
                    Path(project_directory, "new_file.py")
                )

            build.side_effect = update_buck_directory()

            shared_analysis_directory.rebuild()

            self.assertFileIsLinkedBothWays(
                "existing.py",
                shared_analysis_directory,
                original_scratch_directory,
                project_directory,
            )
            self.assertFileIsLinkedBothWays(
                "new_file.py",
                shared_analysis_directory,
                original_scratch_directory,
                project_directory,
            )

            self.assertFalse(
                os.path.lexists(
                    os.path.join(original_scratch_directory, "to_be_deleted.py")
                )
            )
            self.assertNotIn(
                os.path.join(project_directory, "to_be_deleted.py"),
                shared_analysis_directory._symbolic_links,
            )
