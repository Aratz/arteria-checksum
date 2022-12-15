from arteria.web.state import State as arteria_state
from checksum.lib.jobrunner import Job, ChecksumService

import os
import tempfile
import pytest
import logging
import asyncio


class TestJob:
    def test_basic_command(self, caplog):
        job_id = 1
        cmd = ["echo", "test"]
        caplog.set_level(logging.INFO)

        job = Job(job_id, cmd)
        assert job.job_id == job_id
        assert job.cmd == cmd

        job.wait()

        assert job.get_status() == arteria_state.DONE
        assert caplog.records[-1].levelname == "INFO"
        assert caplog.records[-1].msg == (
                f"Starting new job with id {job_id} and command: `{cmd}`")

    def test_stdout_to_file(self):
        job_id = 2
        msg = "test"
        cmd = ["echo", msg]
        stdout = tempfile.NamedTemporaryFile(mode='r')
        job = Job(job_id, cmd, stdout=stdout)

        job.wait()
        stdout.seek(0)

        assert job.get_status() == arteria_state.DONE
        assert stdout.read() == f"{msg}\n"

    def test_set_cwd(self):
        job_id = 3
        filename = "test.txt"
        temp_dir = tempfile.TemporaryDirectory()
        cmd = ["touch", filename]
        job = Job(job_id, cmd, cwd=temp_dir.name)

        job.wait()

        assert os.path.exists('/'.join([temp_dir.name, filename]))

    def test_log_and_raise_exc(self, caplog):
        job_id = 4
        cmd = ["fakecmd"]
        caplog.set_level(logging.INFO)

        with pytest.raises(Exception):
            Job(job_id, cmd)

        assert caplog.records[-1].levelname == "ERROR"

    def test_cancel(self, caplog):
        job_id = 5
        cmd = ["sleep", "60"]
        caplog.set_level(logging.INFO)

        job = Job(job_id, cmd)

        assert job.get_status() == arteria_state.STARTED

        job.cancel()

        assert job.get_status() == arteria_state.CANCELLED
        assert caplog.records[-1].levelname == "INFO"
        assert caplog.records[-1].msg == f"Cancelling job {job_id} (`{cmd}`)"


class TestCheksumService:
    def test_constructor(self):
        history_len = 5
        checksum_service = ChecksumService(history_len)

        assert checksum_service._job_history.maxlen == history_len

    @pytest.mark.asyncio
    async def test_generate_next_id(self):
        checksum_service = ChecksumService(5)

        max_job = 1000

        ids = [checksum_service._generate_next_id() for _ in range(1, max_job)]
        ids = await asyncio.gather(*ids)

        assert sorted(ids) == list(range(1, max_job))

    @pytest.mark.asyncio
    async def test_start(self):
        msg = "test"
        stdout = tempfile.NamedTemporaryFile(mode='r')
        checksum_service = ChecksumService(5)
        await checksum_service.start(["echo", msg], stdout=stdout)

        checksum_service._job_history[0].wait()
        stdout.seek(0)

        assert stdout.read() == f"{msg}\n"
        assert checksum_service._job_history[0].get_status() == arteria_state.DONE

    @pytest.mark.asyncio
    async def test_list_full(self):
        checksum_service = ChecksumService(2)
        with pytest.raises(RuntimeError):
            for _ in range(5):
                await checksum_service.start(["sleep", "10"])

    @pytest.mark.asyncio
    async def test_start_list_full_await(self):
        checksum_service = ChecksumService(2)
        for _ in range(2):
            job_id = await checksum_service.start(["echo", "test"])
            checksum_service._get_job(job_id).wait()

        job_id = await checksum_service.start(["echo", "test"])

        assert checksum_service._job_history[0].job_id == job_id

    @pytest.mark.asyncio
    async def test_start_stress_test(self):
        n_job = 100
        checksum_service = ChecksumService(n_job)
        await asyncio.gather(*[
            checksum_service.start(["echo", "test"]) for _ in range(n_job)])

        for job in checksum_service._job_history:
            job.wait()

        assert len(checksum_service._job_history) == n_job
        assert all(
                job.get_status() == arteria_state.DONE
                for job in checksum_service._job_history)

    @pytest.mark.asyncio
    async def test_stop(self):
        checksum_service = ChecksumService(5)
        job_id = await checksum_service.start(["sleep", "1"])
        checksum_service.stop(job_id)
        checksum_service.stop(10000)

        assert checksum_service.status(job_id) == arteria_state.CANCELLED

    @pytest.mark.asyncio
    async def test_stop_all(self):
        n_job = 5
        checksum_service = ChecksumService(n_job)
        await asyncio.gather(*[
            checksum_service.start(["sleep", "10"]) for _ in range(n_job)])
        checksum_service.stop_all()

        assert all(
                job.get_status() == arteria_state.CANCELLED
                for job in checksum_service._job_history)

    @pytest.mark.asyncio
    async def test_status(self):
        checksum_service = ChecksumService(5)
        job_id = await checksum_service.start(["sleep", "0.05"])
        assert checksum_service.status(job_id) == arteria_state.STARTED
        checksum_service._job_history[0].wait()
        assert checksum_service.status(job_id) == arteria_state.DONE

    @pytest.mark.asyncio
    async def test_status_not_found(self):
        n_job = 5
        checksum_service = ChecksumService(n_job)
        await asyncio.gather(*[
            checksum_service.start(["echo", "test"]) for _ in range(n_job)])

        assert checksum_service.status(10) == arteria_state.NONE

    @pytest.mark.asyncio
    async def test_status_all(self):
        n_job = 5
        checksum_service = ChecksumService(n_job)
        await asyncio.gather(*[
            checksum_service.start(["echo", "test"]) for _ in range(n_job)])

        for job in checksum_service._job_history:
            job.wait()

        assert checksum_service.status_all() == {
                job_id: arteria_state.DONE
                for job_id in range(1, n_job + 1)
                }
