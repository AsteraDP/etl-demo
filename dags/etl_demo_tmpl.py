import json
import os.path
from contextlib import closing
from datetime import timedelta, datetime
from typing import Sequence

from airflow import DAG
from airflow.models import Variable
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import PythonOperator
from airflow.providers.docker.operators.docker import DockerOperator
from airflow.providers.postgres.operators.postgres import PostgresOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook


DAG_NAME = "etl_demo"

default_args = {
    "owner": "testuser",
    "start_date": datetime(2022, 1, 1),
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
}


class ConfigReader:
    template_fields: Sequence[str] = ("config",)

    def __init__(self, dag_id):
        self.config = Variable.get(dag_id.upper() + "_CONFIG")


def load_template(config: ConfigReader):
    # add stuff to config
    print(f"CONFIG USED: {config.config}")
    return json.dumps(json.loads(config.config))


def insert_data_into_tables(project_name, **context):
    pg_hook = PostgresHook.get_hook("pg_dwh_conn")

    raw_telemetry = context['ti'].xcom_pull(task_ids=f'{project_name}_s3')[0].replace("'", '"')
    telemetry = json.loads(raw_telemetry)

    tables = {}
    for sink, tele in telemetry.items():
        for src_file, meta in tele.items():
            ext_path = os.path.dirname(src_file)
            if ext_path in tables:
                tables[ext_path]["files"].append(src_file)
            else:
                meta["files"] = [src_file]
                tables[ext_path] = meta

    table_idx = 1
    mount_path = "/data/s3"
    for table, meta in tables.items():
        for input_file in meta["files"]:
            with open(os.path.join(mount_path, input_file), 'r') as input:
                with closing(pg_hook.get_conn()) as conn:
                    with closing(conn.cursor()) as cur:
                        cur.copy_expert(
                            f"COPY {project_name}_{table_idx} FROM STDIN",
                            input
                        )
                        conn.commit()
        table_idx += 1


def gen_create_table(project_name, **context):
    raw_telemetry = context['ti'].xcom_pull(task_ids=f'{project_name}_s3')[0].replace("'", '"')
    telemetry = json.loads(raw_telemetry)

    tables = {}
    for sink, tele in telemetry.items():
        for src_file, meta in tele.items():
            ext_path = os.path.dirname(src_file)
            tables[ext_path] = meta

    statements = []
    table_idx = 1
    for table, meta in tables.items():
        columns = " text,\n".join(meta["columns"]) + " text"
        statements.append(f"CREATE TABLE IF NOT EXISTS {project_name}_{table_idx} ({columns})")
        table_idx += 1
    return ";\n".join(statements)


with DAG(
  DAG_NAME,
  default_args = default_args,
  schedule_interval = None,
  catchup=False,
) as dag:
    start_dag = EmptyOperator(task_id="start")
    end_dag = EmptyOperator(task_id="end")

    templater = PythonOperator(
        task_id="template_loader",
        python_callable=load_template,
        op_args=[ConfigReader(DAG_NAME)]
    )

    etl = DockerOperator(
        task_id=f"{DAG_NAME}_s3",
        image="registry.astera.gq/piperunner:latest",
        auto_remove="force",
        environment={
            "PIPE_TEMPLATE_CONFIG": "{{ ti.xcom_pull(task_ids='template_loader') }}",
        },
        xcom_all=True,
        docker_url="unix://var/run/docker.sock",
        network_mode="bridge",
        force_pull=True
    )

    create_table_statement_gen = PythonOperator(
        task_id="create_table_statement_generator",
        python_callable=gen_create_table,
        provide_context=True,
        op_kwargs={"project_name": DAG_NAME} 
    )

    create_table = PostgresOperator(
        task_id="create_table",
        postgres_conn_id="pg_dwh_conn",
        sql="{{ ti.xcom_pull(task_ids='create_table_statement_generator') }}",
    )

    insert_data = PythonOperator(
        task_id="insert_data",
        python_callable=insert_data_into_tables,
        provide_context=True,
        op_kwargs={"project_name": DAG_NAME}
    )


start_dag >> templater >> etl >> create_table_statement_gen >> create_table >> insert_data >> end_dag
