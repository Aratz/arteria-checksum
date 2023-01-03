from arteria.web.state import State as arteria_state
from checksum.runner_service import Job, RunnerService

import os
import tempfile
import pytest
import logging
import asyncio


class TestJob:
    def test_basic_command(self, caplog):
        """
        Test basic command is run and logged
        """
        job_id = 1
        cmd = ["echo", "test"]
        caplog.set_level(logging.INFO)

        job = Job(job_id, cmd)
        assert job.job_id == job_id
        assert job.cmd == cmd

        job.wait()

        assert job.get_status() == arteria_state.DONE
        assert caplog.records[0].levelname == "INFO"
        assert caplog.records[0].msg == (
                f"Starting:\n job id: {job_id}\n cmd: {cmd}")

    def test_stdout_to_file(self):
        """
        Test it is possible to redirect stdout to a file.
        """
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
        """
        Test it is possible to set the running directory.
        """
        job_id = 3
        filename = "test.txt"
        temp_dir = tempfile.TemporaryDirectory()
        cmd = ["touch", filename]
        job = Job(job_id, cmd, cwd=temp_dir.name)

        job.wait()

        assert os.path.exists('/'.join([temp_dir.name, filename]))

    def test_log_and_raise_exc(self, caplog):
        """
        Test an exception is raised when an error occurs in the command, and
        that the error is logged.
        """
        job_id = 4
        cmd = ["fakecmd"]
        caplog.set_level(logging.INFO)

        with pytest.raises(Exception):
            Job(job_id, cmd)

        assert caplog.records[-1].levelname == "ERROR"

    def test_cancel(self, caplog):
        """
        Test it is possible to cancel a job and that this action is logged
        """
        job_id = 5
        cmd = ["sleep", "60"]
        caplog.set_level(logging.INFO)

        job = Job(job_id, cmd)

        assert job.get_status() == arteria_state.STARTED

        job.cancel()

        assert job.get_status() == arteria_state.CANCELLED
        assert caplog.records[-1].levelname == "INFO"
        assert caplog.records[-1].msg == f"Cancelling job {job_id} (`{cmd}`)"


class TestRunnerService:
    def test_constructor(self):
        """
        Test is it possible to build a service with the given history length.
        """
        history_len = 5
        checksum_service = RunnerService(history_len)

        assert checksum_service._job_history.maxlen == history_len

    @pytest.mark.asyncio
    async def test_generate_next_id(self):
        """
        Test no two generated ids are the same.
        """
        checksum_service = RunnerService(5)

        max_job = 1000

        ids = [checksum_service._generate_next_id() for _ in range(1, max_job)]
        ids = await asyncio.gather(*ids)

        assert sorted(ids) == list(range(1, max_job))

    @pytest.mark.asyncio
    async def test_start(self):
        """
        Test it is possible to start a job.
        """
        msg = "test"
        stdout = tempfile.NamedTemporaryFile(mode='r')
        checksum_service = RunnerService(5)
        await checksum_service.start(["echo", msg], stdout=stdout)

        checksum_service._job_history[0].wait()
        stdout.seek(0)

        assert stdout.read() == f"{msg}\n"

        status = checksum_service._job_history[0].get_status() 
        assert status == arteria_state.DONE

    @pytest.mark.asyncio
    async def test_list_full(self):
        """
        Test a RuntimeError is raised when trying to start a job but the oldest
        item in the queue is still running.
        """
        checksum_service = RunnerService(2)
        with pytest.raises(RuntimeError):
            for _ in range(5):
                await checksum_service.start(["sleep", "10"])

    @pytest.mark.asyncio
    async def test_start_list_full_await(self):
        """
        Test jobs can be started when the queue is full but all its jobs are
        done.
        """
        checksum_service = RunnerService(2)
        for _ in range(2):
            job_id = await checksum_service.start(["echo", "test"])
            checksum_service._get_job(job_id).wait()

        job_id = await checksum_service.start(["echo", "test"])

        assert checksum_service._job_history[0].job_id == job_id

    @pytest.mark.asyncio
    async def test_start_stress_test(self):
        """
        Test it is possible to start 1000 jobs (almost) simultaneously.
        """
        n_job = 100
        checksum_service = RunnerService(n_job)
        await asyncio.gather(
            *[checksum_service.start(["echo", "test"]) for _ in range(n_job)]
        )

        for job in checksum_service._job_history:
            job.wait()

        assert len(checksum_service._job_history) == n_job
        assert all(
            job.get_status() == arteria_state.DONE
            for job in checksum_service._job_history
        )

    @pytest.mark.asyncio
    async def test_stop(self):
        """
        Test it is possible to stop a job.
        """
        checksum_service = RunnerService(5)
        job_id = await checksum_service.start(["sleep", "1"])
        checksum_service.stop(job_id)
        checksum_service.stop(10000)

        assert checksum_service.status(job_id) == arteria_state.CANCELLED

    @pytest.mark.asyncio
    async def test_stop_all(self):
        """
        Test it is possible to stop all jobs.
        """
        n_job = 5
        checksum_service = RunnerService(n_job)
        await asyncio.gather(
            *[checksum_service.start(["sleep", "10"]) for _ in range(n_job)]
        )
        checksum_service.stop_all()

        assert all(
            job.get_status() == arteria_state.CANCELLED
            for job in checksum_service._job_history
        )

    @pytest.mark.asyncio
    async def test_status(self):
        """
        Test it is possible to get the status of one job.
        """
        checksum_service = RunnerService(5)
        job_id = await checksum_service.start(["sleep", "0.05"])
        assert checksum_service.status(job_id) == arteria_state.STARTED
        checksum_service._job_history[0].wait()
        assert checksum_service.status(job_id) == arteria_state.DONE

    @pytest.mark.asyncio
    async def test_status_not_found(self):
        """
        Test getting status of a non-existing job.
        """
        n_job = 5
        checksum_service = RunnerService(n_job)
        await asyncio.gather(
            *[checksum_service.start(["echo", "test"]) for _ in range(n_job)]
        )

        assert checksum_service.status(10) == arteria_state.NONE

    @pytest.mark.asyncio
    async def test_status_all(self):
        """
        Test getting the status of all jobs.
        """
        n_job = 5
        checksum_service = RunnerService(n_job)
        await asyncio.gather(
            *[checksum_service.start(["echo", "test"]) for _ in range(n_job)]
        )

        for job in checksum_service._job_history:
            job.wait()

        assert checksum_service.status_all() == {
            job_id: arteria_state.DONE
            for job_id in range(1, n_job + 1)
        }
