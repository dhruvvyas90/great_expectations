from great_expectations.execution_engine import (
    PandasExecutionEngine,
    SparkDFExecutionEngine,
)
from great_expectations.execution_engine.sqlalchemy_execution_engine import (
    SqlAlchemyExecutionEngine,
)
from great_expectations.expectations.metrics.column_aggregate_metric import (
    ColumnMetricProvider,
)
from great_expectations.expectations.metrics.column_aggregate_metric import F as F
from great_expectations.expectations.metrics.column_aggregate_metric import (
    column_aggregate_metric,
)
from great_expectations.expectations.metrics.column_aggregate_metric import sa as sa


class ColumnSum(ColumnMetricProvider):
    metric_name = "column.aggregate.sum"

    @column_aggregate_metric(engine=PandasExecutionEngine)
    def _pandas(cls, column, **kwargs):
        return column.sum()

    @column_aggregate_metric(engine=SqlAlchemyExecutionEngine)
    def _sqlalchemy(cls, column, **kwargs):
        return sa.func.sum(column)

    @column_aggregate_metric(engine=SparkDFExecutionEngine)
    def _spark(cls, column, **kwargs):
        return F.sum(column)
