"""Offline artifact-fetch regressions using GitHub's documented page semantics."""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit

spec = importlib.util.spec_from_file_location('job_tool', Path(__file__).with_name('job.py'))
job_tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job_tool)


class ActionsArtifactTests(unittest.TestCase):
    def fetch(self, count, fail_page=None):
        artifacts = [{'id': i, 'name': f'shard-{i}', 'size_in_bytes': len(str(i)),
                      'archive_download_url': f'https://example.invalid/artifacts/{i}'}
                     for i in range(count)]
        listed, downloaded = [], []

        def api(path):
            query = parse_qs(urlsplit(path).query)
            size = int(query.get('per_page', ['30'])[0])
            page = int(query.get('page', ['1'])[0])
            self.assertGreater(size, 0)
            self.assertLessEqual(size, 100)
            listed.append(page)
            if page == fail_page:
                raise OSError('offline page failure')
            start = (page - 1) * size
            return {'total_count': count, 'artifacts': artifacts[start:start + size]}

        def download(request, **kwargs):
            index = int(request.full_url.rsplit('/', 1)[1])
            downloaded.append(index)
            return io.BytesIO(str(index).encode())

        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(job_tool, 'gh_api', side_effect=api), \
                 mock.patch.object(job_tool, 'gh_token', return_value='offline-fixture'), \
                 mock.patch.object(job_tool.urllib.request, 'urlopen', side_effect=download), \
                 contextlib.redirect_stdout(io.StringIO()):
                if fail_page:
                    with self.assertRaisesRegex(OSError, 'offline page failure'):
                        job_tool.actions_fetch(123, directory)
                    self.assertFalse(list(Path(directory).rglob('*.zip')))
                    self.assertEqual(downloaded, [])
                    return
                job_tool.actions_fetch(123, directory)
            self.assertEqual(sorted(downloaded), list(range(count)))
            self.assertEqual(len(set(downloaded)), len(downloaded))
            for item in artifacts:
                self.assertEqual((Path(directory) / 'result' / (item['name'] + '.zip')).read_bytes(),
                                 str(item['id']).encode())
            self.assertEqual(listed, list(range(1, len(listed) + 1)))

    def test_empty_run(self):
        self.fetch(0)

    def test_single_page(self):
        self.fetch(7)

    def test_all_artifacts_beyond_default_and_maximum_page_sizes(self):
        for count in (31, 101, 200):
            with self.subTest(count=count):
                self.fetch(count)

    def test_later_listing_failure_does_not_look_like_a_complete_fetch(self):
        self.fetch(101, fail_page=2)


if __name__ == '__main__':
    unittest.main()
