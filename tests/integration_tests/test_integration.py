import json
import logging
import os
import shutil
import tempfile
import time
import yaml

from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application
from tornado.escape import json_encode

from arteria.web.app import AppService
from arteria.web.state import State

from checksum.app import routes as app_routes, compose_application

from tests.test_utils import DUMMY_CONFIG, gen_dummy_data

log = logging.getLogger(__name__)


class TestIntegration(AsyncHTTPTestCase):
    API_BASE = "/api/1.0"

    def get_app(self):
        path_to_this_file = os.path.abspath(
            os.path.dirname(os.path.realpath(__file__)))

        self.config = tempfile.TemporaryDirectory()
        with open(f"{self.config.name}/app.config", mode='w') as f:
            f.write(yaml.dump(DUMMY_CONFIG))
        shutil.copyfile(
                f"{path_to_this_file}/../../config/logger.config",
                f"{self.config.name}/logger.config")

        app_svc = AppService.create(
                product_name="test_checksum_service",
                config_root=self.config.name,
                args=[])

        config = app_svc.config_svc
        composed_application = compose_application(config)
        routes = app_routes(**composed_application)

        return Application(routes)

    def _test_checksum_folder(self, url, body):
        response = self.fetch(url, method="POST", body=json_encode(body))

        assert response.code == 202
        response_as_json = json.loads(response.body)

        assert response_as_json["state"] == State.STARTED

        status = self.fetch(response_as_json["link"])
        status_as_json = json.loads(status.body)

        while status_as_json["state"] == State.STARTED:
            time.sleep(0.5)
            status = self.fetch(response_as_json["link"])
            status_as_json = json.loads(status.body)

        return status_as_json["state"]


class TestIntegrationSmall(TestIntegration):
    def setUp(self):
        super().setUp()

        self.folder, self.checksum_file = gen_dummy_data(10**4)  # 10KB
        self.foldername = self.folder.name.split('/')[-1]

    def test_checksum(self):
        """
        Test checking a sane file returns state done.
        """
        url = self.API_BASE + f"/start/{self.foldername}"
        body = {"path_to_md5_sum_file": self.checksum_file}

        assert self._test_checksum_folder(url, body) == State.DONE

    def test_checksum_corrupt(self):
        """
        Test checking a corrupt file returns an error.
        """
        with open("/".join([self.folder.name, "file0.bin"]), 'wb') as f:
            f.write(os.urandom(10))

        url = self.API_BASE + f"/start/{self.foldername}"
        body = {"path_to_md5_sum_file": self.checksum_file}

        assert self._test_checksum_folder(url, body) == State.ERROR

    def test_multiple_checksum(self):
        """
        Test multiple jobs can be launched simultaneously and jobs can still be
        launched when the history is full.
        """
        url = self.API_BASE + f"/start/{self.foldername}"
        body = {"path_to_md5_sum_file": self.checksum_file}

        for _ in range(2):
            responses = [
                    self.fetch(url, method="POST", body=json_encode(body))
                    for _ in range(10)]

            assert all(response.code == 202 for response in responses)

            for response in responses:
                response_as_json = json.loads(response.body)

                status = self.fetch(response_as_json["link"])
                status_as_json = json.loads(status.body)

                while status_as_json["state"] == State.STARTED:
                    time.sleep(0.5)
                    status = self.fetch(response_as_json["link"])
                    status_as_json = json.loads(status.body)

            statuses = [
                    json.loads(
                        self.fetch(json.loads(response.body)["link"]).body)
                    for response in responses]

            assert all(status["state"] == State.DONE for status in statuses)

    def test_status_all(self):
        """
        Test getting all statuses at the same time.
        """
        url = self.API_BASE + f"/start/{self.foldername}"
        body = {"path_to_md5_sum_file": self.checksum_file}
        n_jobs = 10
        for _ in range(n_jobs):
            self.fetch(url, method="POST", body=json_encode(body))

        url = self.API_BASE + "/status/"
        status_as_json = json.loads(self.fetch(url, method="GET").body)
        assert len(status_as_json) == n_jobs
        assert all(
            job["state"] == State.DONE
            for job in json.loads(
                self.fetch(url, method="GET").body).values())

    def test_start_checksum_with_shell_injection(self):
        """
        Test shell injections are intercepted.
        """
        body = {"path_to_md5_sum_file": "tests/$(cat /etc/shadow)"}
        response = self.fetch(
            self.API_BASE + "/start/ok_checksums",
            method="POST",
            body=json_encode(body))

        assert response.code == 500


class TestIntegrationBig(TestIntegration):
    def setUp(self):
        super().setUp()

        self.folder, self.checksum_file = gen_dummy_data(10**7)  # 10MB
        self.foldername = self.folder.name.split('/')[-1]

    def test_stop(self):
        url = self.API_BASE + f"/start/{self.foldername}"
        body = {"path_to_md5_sum_file": self.checksum_file}

        response = self.fetch(url, method="POST", body=json_encode(body))

        assert response.code == 202
        response_as_json = json.loads(response.body)

        assert response_as_json["state"] == State.STARTED

        job_id = response_as_json["job_id"]
        link = response_as_json["link"]

        url = self.API_BASE + f"/stop/{job_id}"
        response = self.fetch(url, method="POST", body="")
        assert response.code == 200

        status = json.loads(self.fetch(link, method="GET").body)
        assert status["state"] == State.CANCELLED

    def test_stop_all(self):
        url = self.API_BASE + f"/start/{self.foldername}"
        body = {"path_to_md5_sum_file": self.checksum_file}
        n_jobs = 5
        for _ in range(n_jobs):
            self.fetch(url, method="POST", body=json_encode(body))

        url = self.API_BASE + "/stop/all"
        response = self.fetch(url, method="POST", body="")
        assert response.code == 200

        url = self.API_BASE + "/status/"
        assert all(
            job["state"] == State.CANCELLED
            for job in json.loads(
                self.fetch(url, method="GET").body).values())
