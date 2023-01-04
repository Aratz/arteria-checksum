import os
import json
import mock

from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application
from tornado.escape import json_encode

from arteria.web.state import State

from checksum.app import routes
from checksum import __version__ as checksum_version
from checksum.checksum_handlers import StartHandler
from checksum.runner_service import RunnerService
from tests.test_utils import DummyConfig


class TestChecksumHandlers(AsyncHTTPTestCase):

    API_BASE = "/api/1.0"

    runner_service = RunnerService()

    def get_app(self):
        return Application(
            routes(
                config=DummyConfig(),
                runner_service=self.runner_service))

    ok_runfolder = "tests/resources/ok_checksums"


class TestStartHandler(TestChecksumHandlers):
    @mock.patch("os.path.isdir", return_value=True)
    @mock.patch("os.listdir", return_value=["ok_checksums", "rf2", "rf3"])
    def test__validate_runfolder_exists_ok(self, mock_listdir, mock_isdir):
        assert StartHandler._validate_runfolder_exists(
                "ok_checksums", "tests/resources/")

    @mock.patch("os.path.isdir", return_value=False)
    def test__validate_runfolder_exists_not_ok(self, mock_isdir):
        assert not StartHandler._validate_runfolder_exists(
                "invalid_checksums", "tests/resources/")

    @mock.patch("os.path.isfile", return_value=True)
    def test__validate_md5sum_path_ok(self, mock_isfile):
        assert StartHandler._validate_md5sum_path(
                runfolder=TestChecksumHandlers.ok_runfolder,
                md5sum_file_path=os.path.join(
                    TestChecksumHandlers.ok_runfolder, "md5_checksums")
                )

    @mock.patch("os.path.isfile", return_value=True)
    def test__validate_md5sum_nested_path_ok(self, mock_isfile):
        nested_runfolder = "tests/resources/ok_nested_dir/"
        assert StartHandler._validate_md5sum_path(
                runfolder=nested_runfolder,
                md5sum_file_path=os.path.join(
                    nested_runfolder, "./md5sums/empty_file"))

    @mock.patch("os.path.isfile", return_value=False)
    def test__validate_md5sum_path_not_ok(self, mock_isfile):
        assert not StartHandler._validate_md5sum_path(
                runfolder=TestChecksumHandlers.ok_runfolder,
                md5sum_file_path=os.path.join(
                    TestChecksumHandlers.ok_runfolder, "no_file"))

    @mock.patch(
            "checksum.runner_service.RunnerService.start",
            return_value=1)
    @mock.patch(
            "checksum.checksum_handlers"
            ".StartHandler._validate_runfolder_exists",
            return_value=True)
    @mock.patch(
            "checksum.checksum_handlers"
            ".StartHandler._validate_md5sum_path",
            return_value=True)
    @mock.patch(
            "checksum.checksum_handlers"
            ".StartHandler._is_valid_log_dir",
            return_value=True)
    def test_start_checksum(
            self,
            mock_valid_log,
            mock_valid_md5sum_path,
            mock_runfolder_exists,
            mock_start,
            ):
        job_id = mock_start.return_value

        body = {"path_to_md5_sum_file": "md5_checksums"}
        response = self.fetch(
            self.API_BASE + "/start/ok_checksums",
            method="POST",
            body=json_encode(body))

        response_as_json = json.loads(response.body)

        self.assertEqual(response.code, 202)
        self.assertEqual(response_as_json["job_id"], job_id)
        self.assertEqual(response_as_json["service_version"], checksum_version)

        expected_link = (
                f"http://127.0.0.1:{self.get_http_port()}/"
                f"api/1.0/status/{job_id}")
        self.assertEqual(response_as_json["link"], expected_link)
        self.assertEqual(response_as_json["state"], State.STARTED)

    def test_raise_exception_on_log_dir_problem(self):
        with mock.patch(
                "checksum.checksum_handlers.StartHandler._is_valid_log_dir",
                return_value=False):
            body = {"path_to_md5_sum_file": "md5_checksums"}
            response = self.fetch(
                    self.API_BASE + "/start/ok_checksums",
                    method="POST",
                    body=json_encode(body))

            self.assertEqual(response.code, 500)


class TestStatusHandler(TestChecksumHandlers):
    def test_check_status(self):
        with mock.patch(
                "checksum.runner_service.RunnerService.status",
                return_value=State.DONE) as m:
            response = self.fetch(self.API_BASE + "/status/1")
            response_as_json = json.loads(response.body)
            self.assertEqual(response_as_json["state"], State.DONE)
            m.assert_called_once_with(1)


class TestStopHandler(TestChecksumHandlers):
    def test_stop_all_checksum(self):
        with mock.patch("checksum.runner_service.RunnerService.stop_all") as m:
            response = self.fetch(
                    self.API_BASE + "/stop/all", method="POST", body="")
            self.assertEqual(response.code, 200)
            m.assert_called_once()

    def test_stop_one_checksum(self):
        with mock.patch("checksum.runner_service.RunnerService.stop") as m:
            response = self.fetch(
                    self.API_BASE + "/stop/1", method="POST", body="")
            self.assertEqual(response.code, 200)
            m.assert_called_once_with(1)

    def test_version(self):
        response = self.fetch(self.API_BASE + "/version")

        expected_result = {"version": checksum_version}

        self.assertEqual(response.code, 200)
        self.assertEqual(json.loads(response.body), expected_result)
