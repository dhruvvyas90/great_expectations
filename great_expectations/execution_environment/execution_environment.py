import copy
import logging
from typing import Any, Callable, Dict, List, Optional, Union

from great_expectations.core.batch import (
    Batch,
    BatchDefinition,
    BatchMarkers,
    BatchRequest,
    PartitionRequest,
)
from great_expectations.data_context.util import instantiate_class_from_config
from great_expectations.execution_engine import ExecutionEngine
from great_expectations.execution_environment.data_connector import DataConnector
from great_expectations.execution_environment.types import PathBatchSpec

logger = logging.getLogger(__name__)


class BaseExecutionEnvironment:
    """
    An ExecutionEnvironment is the glue between an ExecutionEngine and a DataConnector.
    """

    recognized_batch_parameters: set = {"limit"}

    def __init__(
        self,
        name: str,
        execution_engine=None,
        data_context_root_directory: Optional[str] = None,
    ):
        """
        Build a new ExecutionEnvironment.

        Args:
            name: the name for the datasource
            execution_engine (ClassConfig): the type of compute engine to produce
            data_context_root_directory: Installation directory path (if installed on a filesystem).
        """
        self._name = name

        self._data_context_root_directory = data_context_root_directory

        self._execution_engine = instantiate_class_from_config(
            config=execution_engine,
            runtime_environment={},
            config_defaults={"module_name": "great_expectations.execution_engine"},
        )

        self._execution_environment_config = {
            "execution_engine": execution_engine,
        }

        self._data_connectors = {}

    def get_batch_from_batch_definition(
        self, batch_definition: BatchDefinition, batch_data: Any = None,
    ) -> Batch:
        """
        Note: this method should *not* be used when getting a Batch from a BatchRequest, since it does not capture BatchRequest metadata.
        """
        if not isinstance(batch_data, type(None)):
            # TODO: <Alex>Abe: Are the comments below still pertinent?  Or can they be deleted?</Alex>
            # NOTE Abe 20201014: Maybe do more careful type checking here?
            # Seems like we should verify that batch_data is compatible with the execution_engine...?
            batch_spec, batch_markers = None, None
        else:
            data_connector: DataConnector = self.data_connectors[
                batch_definition.data_connector_name
            ]
            (
                batch_data,
                batch_spec,
                batch_markers,
            ) = data_connector.get_batch_data_and_metadata(
                batch_definition=batch_definition
            )
        new_batch: Batch = Batch(
            data=batch_data,
            batch_request=None,
            batch_definition=batch_definition,
            batch_spec=batch_spec,
            batch_markers=batch_markers,
        )
        return new_batch

    def get_single_batch_from_batch_request(self, batch_request: BatchRequest) -> Batch:
        batch_list = self.get_batch_list_from_batch_request(batch_request)
        if len(batch_list) != 1:
            raise ValueError(
                f"Got {len(batch_list)} batches instead of a single batch."
            )
        return batch_list[0]

    def get_batch_list_from_batch_request(
        self, batch_request: BatchRequest
    ) -> List[Batch]:
        """
        Processes batch_request and returns the (possibly empty) list of batch objects.

        Args:
            :batch_request encapsulation of request parameters necessary to identify the (possibly multiple) batches
            :returns possibly empty list of batch objects; each batch object contains a dataset and associated metatada
        """
        self._validate_batch_request(batch_request=batch_request)

        data_connector: DataConnector = self.data_connectors[
            batch_request.data_connector_name
        ]
        batch_definition_list: List[
            BatchDefinition
        ] = data_connector.get_batch_definition_list_from_batch_request(
            batch_request=batch_request
        )

        if batch_request["batch_data"] is None:
            batches: List[Batch] = []
            for batch_definition in batch_definition_list:
                batch_definition.batch_spec_passthrough = (
                    batch_request.batch_spec_passthrough
                )
                batch_data: Any
                batch_spec: PathBatchSpec
                batch_markers: BatchMarkers
                (
                    batch_data,
                    batch_spec,
                    batch_markers,
                ) = data_connector.get_batch_data_and_metadata(
                    batch_definition=batch_definition
                )
                new_batch: Batch = Batch(
                    data=batch_data,
                    batch_request=batch_request,
                    batch_definition=batch_definition,
                    batch_spec=batch_spec,
                    batch_markers=batch_markers,
                )
                batches.append(new_batch)
            return batches

        else:
            # This is a runtime batchrequest

            if len(batch_definition_list) != 1:
                raise ValueError(
                    "When batch_request includes batch_data, it must specify exactly one corresponding BatchDefinition"
                )

            batch_definition = batch_definition_list[0]
            batch_data = batch_request["batch_data"]

            # noinspection PyArgumentList
            (
                typed_batch_data,
                batch_spec,
                batch_markers,
            ) = data_connector.get_batch_data_and_metadata(
                batch_definition=batch_definition, batch_data=batch_data,
            )

            new_batch: Batch = Batch(
                data=typed_batch_data,
                batch_request=batch_request,
                batch_definition=batch_definition,
                batch_spec=batch_spec,
                batch_markers=batch_markers,
            )

            return [new_batch]

    def _build_data_connector_from_config(
        self, name: str, config: Dict[str, Any],
    ) -> DataConnector:
        """Build a DataConnector using the provided configuration and return the newly-built DataConnector."""
        new_data_connector: DataConnector = instantiate_class_from_config(
            config=config,
            runtime_environment={
                "name": name,
                "execution_environment_name": self.name,
                "execution_engine": self.execution_engine,
            },
            config_defaults={
                "module_name": "great_expectations.execution_environment.data_connector"
            },
        )
        new_data_connector.data_context_root_directory = (
            self._data_context_root_directory
        )

        self.data_connectors[name] = new_data_connector
        return new_data_connector

    def get_available_data_asset_names(
        self, data_connector_names: Optional[Union[list, str]] = None
    ) -> dict:
        """
        Returns a dictionary of data_asset_names that the specified data
        connector can provide. Note that some data_connectors may not be
        capable of describing specific named data assets, and some (such as
        inferred_asset_data_connector) require the user to configure
        data asset names.

        Args:
            data_connector_names: the DataConnector for which to get available data asset names.

        Returns:
            dictionary consisting of sets of data assets available for the specified data connectors:
            ::

                {
                  data_connector_name: {
                    names: [ (data_asset_1, data_asset_1_type), (data_asset_2, data_asset_2_type) ... ]
                  }
                  ...
                }
        """
        available_data_asset_names: dict = {}
        if data_connector_names is None:
            data_connector_names = self.data_connectors.keys()
        elif isinstance(data_connector_names, str):
            data_connector_names = [data_connector_names]

        for data_connector_name in data_connector_names:
            data_connector: DataConnector = self.data_connectors[data_connector_name]
            available_data_asset_names[
                data_connector_name
            ] = data_connector.get_available_data_asset_names()

        return available_data_asset_names

    def get_available_batch_definitions(
        self, batch_request: BatchRequest
    ) -> List[BatchDefinition]:
        self._validate_batch_request(batch_request=batch_request)

        data_connector: DataConnector = self.data_connectors[
            batch_request.data_connector_name
        ]
        batch_definition_list = data_connector.get_batch_definition_list_from_batch_request(
            batch_request=batch_request
        )

        return batch_definition_list

    def self_check(self, pretty_print=True, max_examples=3):
        report_object = {
            "execution_engine": {
                "class_name": self.execution_engine.__class__.__name__,
            }
        }

        if pretty_print:
            print(f"Execution engine: {self.execution_engine.__class__.__name__}")

        if pretty_print:
            print(f"Data connectors:")

        data_connector_list = list(self.data_connectors.keys())
        data_connector_list.sort()
        report_object["data_connectors"] = {"count": len(data_connector_list)}

        for data_connector_name in data_connector_list:
            data_connector_obj: DataConnector = self.data_connectors[
                data_connector_name
            ]
            data_connector_return_obj = data_connector_obj.self_check(
                pretty_print=pretty_print, max_examples=max_examples
            )
            report_object["data_connectors"][
                data_connector_name
            ] = data_connector_return_obj

        return report_object

    def _validate_batch_request(self, batch_request: BatchRequest):
        if not (
            batch_request.execution_environment_name is None
            or batch_request.execution_environment_name == self.name
        ):
            raise ValueError(
                f"""execution_envrironment_name in BatchRequest: "{batch_request.execution_environment_name}" does not
                match ExecutionEnvironment name: "{self.name}".
                """
            )

    @property
    def name(self) -> str:
        """
        Property for datasource name
        """
        return self._name

    @property
    def execution_engine(self) -> ExecutionEngine:
        return self._execution_engine

    @property
    def data_connectors(self):
        return self._data_connectors

    @property
    def config(self):
        return copy.deepcopy(self._execution_environment_config)


class ExecutionEnvironment(BaseExecutionEnvironment):
    """
    An ExecutionEnvironment is the glue between an ExecutionEngine and a DataConnector.
    """

    recognized_batch_parameters: set = {"limit"}

    def __init__(
        self,
        name: str,
        execution_engine=None,
        data_connectors=None,
        data_context_root_directory: Optional[str] = None,
    ):
        """
        Build a new ExecutionEnvironment with data connectors.

        Args:
            name: the name for the datasource
            execution_engine (ClassConfig): the type of compute engine to produce
            data_connectors: DataConnectors to add to the datasource
            data_context_root_directory: Installation directory path (if installed on a filesystem).
        """
        self._name = name

        super().__init__(
            name=name,
            execution_engine=execution_engine,
            data_context_root_directory=data_context_root_directory,
        )

        if data_connectors is None:
            data_connectors = {}
        self._data_connectors = data_connectors
        self._init_data_connectors(data_connector_configs=data_connectors)

        self._execution_environment_config.update({"data_connectors": data_connectors})

    def _init_data_connectors(
        self, data_connector_configs: Dict[str, Dict[str, Any]],
    ):
        for name, config in data_connector_configs.items():
            self._build_data_connector_from_config(
                name=name, config=config,
            )
