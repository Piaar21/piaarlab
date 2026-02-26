import uuid
from collections import defaultdict
from datetime import timedelta

from django.core.management.base import BaseCommand

from traffic_management.models import Task


class UnionFind:
    def __init__(self, ids):
        self.parent = {obj_id: obj_id for obj_id in ids}
        self.rank = {obj_id: 0 for obj_id in ids}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        root_a = self.find(a)
        root_b = self.find(b)
        if root_a == root_b:
            return
        if self.rank[root_a] < self.rank[root_b]:
            self.parent[root_a] = root_b
        elif self.rank[root_a] > self.rank[root_b]:
            self.parent[root_b] = root_a
        else:
            self.parent[root_b] = root_a
            self.rank[root_a] += 1


class Command(BaseCommand):
    help = (
        "Backfill Task.campaign_id and Task.cycle_no. "
        "Grouping rule: original_task chain OR same (product, keyword) "
        "within the configured gap window."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--gap-days",
            type=int,
            default=90,
            help="Maximum gap days between prior end and next start to keep same campaign (default: 90).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without writing to database.",
        )

    def handle(self, *args, **options):
        gap_days = options["gap_days"]
        dry_run = options["dry_run"]
        gap_delta = timedelta(days=gap_days)

        tasks = list(
            Task.objects.only(
                "id",
                "product_id",
                "keyword_id",
                "available_start_date",
                "available_end_date",
                "original_task_id",
                "campaign_id",
                "cycle_no",
            ).order_by("id")
        )
        if not tasks:
            self.stdout.write(self.style.WARNING("No Task rows found."))
            return

        uf = UnionFind([task.id for task in tasks])
        task_by_id = {task.id: task for task in tasks}

        # Rule 1: keep original_task chain together.
        chain_edges = 0
        for task in tasks:
            parent_id = task.original_task_id
            if parent_id and parent_id in task_by_id:
                uf.union(task.id, parent_id)
                chain_edges += 1

        # Rule 2: same product + keyword with <= gap-days continuity.
        buckets = defaultdict(list)
        for task in tasks:
            if task.product_id is None or task.keyword_id is None:
                continue
            buckets[(task.product_id, task.keyword_id)].append(task)

        continuity_edges = 0
        for bucket_tasks in buckets.values():
            bucket_tasks.sort(key=lambda t: (t.available_start_date, t.id))
            previous = None
            for current in bucket_tasks:
                if previous is not None:
                    if current.available_start_date - previous.available_end_date <= gap_delta:
                        uf.union(previous.id, current.id)
                        continuity_edges += 1
                previous = current

        components = defaultdict(list)
        for task in tasks:
            components[uf.find(task.id)].append(task)

        to_update = []
        for comp_tasks in components.values():
            comp_tasks.sort(key=lambda t: (t.available_start_date, t.id))
            existing_campaigns = sorted({str(t.campaign_id) for t in comp_tasks if t.campaign_id})

            if existing_campaigns:
                campaign_uuid = uuid.UUID(existing_campaigns[0])
            else:
                seed_task_id = comp_tasks[0].id
                campaign_uuid = uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"traffic-task-campaign:{seed_task_id}",
                )

            for idx, task in enumerate(comp_tasks, start=1):
                if task.campaign_id != campaign_uuid or task.cycle_no != idx:
                    task.campaign_id = campaign_uuid
                    task.cycle_no = idx
                    to_update.append(task)

        self.stdout.write(
            f"Scanned {len(tasks)} tasks / {len(components)} campaign groups "
            f"(chain edges: {chain_edges}, continuity edges: {continuity_edges}, gap: {gap_days} days)."
        )
        self.stdout.write(f"Rows requiring update: {len(to_update)}")

        if dry_run:
            preview_count = min(20, len(to_update))
            if preview_count:
                self.stdout.write("Preview (first rows):")
                for task in to_update[:preview_count]:
                    self.stdout.write(
                        f"  - task_id={task.id}, campaign_id={task.campaign_id}, cycle_no={task.cycle_no}"
                    )
            self.stdout.write(self.style.WARNING("Dry-run mode: no database changes applied."))
            return

        if to_update:
            Task.objects.bulk_update(to_update, ["campaign_id", "cycle_no"], batch_size=1000)
        self.stdout.write(self.style.SUCCESS(f"Backfill completed. Updated {len(to_update)} rows."))
