from django.db import migrations

class Migration(migrations.Migration):
    atomic = False  # 이 마이그레이션은 atomic하지 않음

    dependencies = [
        ('traffic_management', '0021_merge_20250310_1630'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                PRAGMA foreign_keys=off;
                BEGIN TRANSACTION;
                -- 새 테이블 생성: FK 제약조건이 올바르게 Task 테이블을 참조하도록 수정합니다.
                CREATE TABLE traffic_management_navermarketingcost_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE NOT NULL,
                    cost DECIMAL NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    task_id BIGINT NOT NULL REFERENCES traffic_management_task(id) DEFERRABLE INITIALLY DEFERRED,
                    CONSTRAINT traffic_management_navermarketingcost_task_id_date_uniq UNIQUE (task_id, date)
                );
                -- 기존 데이터 복사
                INSERT INTO traffic_management_navermarketingcost_new (id, date, cost, created_at, updated_at, task_id)
                SELECT id, date, cost, created_at, updated_at, task_id FROM traffic_management_navermarketingcost;
                DROP TABLE traffic_management_navermarketingcost;
                ALTER TABLE traffic_management_navermarketingcost_new RENAME TO traffic_management_navermarketingcost;
                COMMIT;
                PRAGMA foreign_keys=on;
            """,
            reverse_sql="""
                SELECT 'Reverse migration not implemented';
            """
        ),
    ]
