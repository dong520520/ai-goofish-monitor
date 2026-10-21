import asyncio

from src.domain.models.task import Task
from src.services.scheduler_service import SchedulerService


def test_task_reload_preserves_local_sync_deadline_and_updates_task_cron():
    async def check():
        service = SchedulerService(object())
        await service.reload_jobs([])
        pending_sync = service.scheduler.get_job("opportunity_local_sync")
        await service.reload_jobs([])
        assert service.scheduler.get_job("opportunity_local_sync") is pending_sync
        assert len(service.scheduler.get_jobs()) == 1
        # Keep every job paused: this test never runs a collector or local sync.
        service.scheduler.start(paused=True)
        try:
            task = Task(id=1, task_name="synthetic", enabled=True,
                        keyword="synthetic", max_pages=1, personal_only=False,
                        cron="*/15 * * * *", ai_prompt_base_file="",
                        ai_prompt_criteria_file="", decision_mode="keyword",
                        keyword_rules=["synthetic"])
            await service.reload_jobs([task])
            sync_job = service.scheduler.get_job("opportunity_local_sync")
            deadline = sync_job.next_run_time
            assert service.scheduler.get_job("task_1") is not None

            for minute in (20, 30, 45):
                await service.reload_jobs([task.model_copy(update={"cron": f"*/{minute} * * * *"})])
                assert service.scheduler.get_job("opportunity_local_sync") is sync_job
                assert sync_job.next_run_time == deadline
                assert len(service.scheduler.get_jobs()) == 2
                assert str(service.scheduler.get_job("task_1").trigger.fields[6]) == f"*/{minute}"

            await service.reload_jobs([task.model_copy(update={"enabled": False})])
            assert service.scheduler.get_job("task_1") is None
            assert service.scheduler.get_job("opportunity_local_sync") is sync_job
            assert sync_job.next_run_time == deadline
            await service.reload_jobs([])
            assert len(service.scheduler.get_jobs()) == 1
            assert sync_job.next_run_time == deadline
        finally:
            service.scheduler.shutdown(wait=False)

    asyncio.run(check())
