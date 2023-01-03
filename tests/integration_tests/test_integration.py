import json
import logging
import os
import time

from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application
from tornado.escape import json_encode

from arteria.web.app import AppService
from arteria.web.state import State

from checksum.app import routes as app_routes, compose_application

log = logging.getLogger(__name__)


class TestIntegration(AsyncHTTPTestCase):
    API_BASE = "/api/1.0"

    def get_app(self):
        path_to_this_file = os.path.abspath(
            os.path.dirname(os.path.realpath(__file__)))
        app_svc = AppService.create(
                product_name="test_checksum_service",
                config_root="{}/../../config/".format(path_to_this_file),
                args=[])

        config = app_svc.config_svc
        composed_application = compose_application(config)
        routes = app_routes(**composed_application)

        return Application(routes)

    def _test_checksum_folder(self, url, body):
        response = self.fetch(
            url,
            method="POST",
            body=json_encode(body))

        self.assertEqual(response.code, 202)
        response_as_json = json.loads(response.body)

        self.assertEqual(response_as_json["state"], State.STARTED)

        status = self.fetch(response_as_json["link"])
        status_as_json = json.loads(status.body)

        while status_as_json["state"] == State.STARTED:
            time.sleep(0.5)
            status = self.fetch(response_as_json["link"])
            status_as_json = json.loads(status.body)

        return status_as_json["state"]

    def test_checksum(self):
        url = self.API_BASE + "/start/ok_checksums"
        body = {"path_to_md5_sum_file": "md5_checksums"}

        assert self._test_checksum_folder(url, body) == State.DONE

    def test_checksum_corrupt(self):
        url = self.API_BASE + "/start/ko_checksums"
        body = {"path_to_md5_sum_file": "md5_checksums"}

        assert self._test_checksum_folder(url, body) == State.ERROR

    def test_start_checksum_with_shell_injection(self):
        body = {"path_to_md5_sum_file": "tests/$(cat /etc/shadow)"}
        response = self.fetch(
            self.API_BASE + "/start/ok_checksums",
            method="POST",
            body=json_encode(body))

        self.assertEqual(response.code, 500)
