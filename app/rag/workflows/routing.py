"""
Routing Workflow Pattern.

Dynamic routing based on query classification or intent detection.
Routes queries to specialized handlers.

Pattern: Classify -> Route -> Handler -> Result
"""


from collections.abc import Awaitable, Callable
from typing import Any

from app.rag.core.logging import get_logger
from app.rag.workflows.base import (
    BaseWorkflow,
    WorkflowMode,
    WorkflowResult,
)

logger = get_logger("rag.workflows.routing")


class RouteHandler:
    """A route handler with its trigger condition."""

    def __init__(
        self,
        name: str,
        handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
        description: str = "",
    ):
        self.name = name
        self.handler = handler
        self.description = description

    async def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Execute the handler."""
        return await self.handler(state)


class RoutingWorkflow(BaseWorkflow):
    """
    Routing workflow dynamically selects handlers based on query.

    Uses a classifier to determine which handler should process
    the query, then routes to that handler.

    Usage:
        workflow = RoutingWorkflow(classifier=my_classifier)
        workflow.add_route("technical", tech_handler, "Technical questions")
        workflow.add_route("general", general_handler, "General questions")
        result = await workflow.run({"question": "..."})
    """

    def __init__(
        self,
        classifier: Callable[[str], Awaitable[str]] | None = None,
        default_route: str = "default",
        **kwargs,
    ):
        """
        Initialize the routing workflow.

        Args:
            classifier: Async function that classifies query -> route name
            default_route: Default route if classification fails
            **kwargs: Additional configuration
        """
        super().__init__(**kwargs)
        self._classifier = classifier
        self._routes: dict[str, RouteHandler] = {}
        self._default_route = default_route

    @property
    def mode(self) -> WorkflowMode:
        return WorkflowMode.ROUTING

    def add_route(
        self,
        name: str,
        handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
        description: str = "",
    ) -> "RoutingWorkflow":
        """
        Add a route handler.

        Args:
            name: Route name (must match classifier output)
            handler: Handler function
            description: Description of what this route handles

        Returns:
            Self for chaining
        """
        self._routes[name] = RouteHandler(name, handler, description)
        return self

    def set_classifier(
        self,
        classifier: Callable[[str], Awaitable[str]],
    ) -> "RoutingWorkflow":
        """Set the query classifier."""
        self._classifier = classifier
        return self

    def set_default_route(self, route: str) -> "RoutingWorkflow":
        """Set the default route."""
        self._default_route = route
        return self

    def get_route_descriptions(self) -> dict[str, str]:
        """Get all route descriptions."""
        return {name: handler.description for name, handler in self._routes.items()}

    async def classify(self, query: str) -> str:
        """
        Classify a query to determine the route.

        Args:
            query: Query to classify

        Returns:
            Route name
        """
        if self._classifier is None:
            return self._default_route

        try:
            route = await self._classifier(query)
            if route not in self._routes:
                logger.warning("Classified route '%s' not found, using default", route)
                return self._default_route
            return route
        except Exception as e:
            logger.error("Classification failed: %s", e)
            return self._default_route

    async def run(self, state: dict[str, Any]) -> WorkflowResult:
        """
        Execute the routing workflow.

        Args:
            state: Initial state

        Returns:
            WorkflowResult with final state
        """
        if not self.validate_state(state):
            return self.create_result(
                state,
                success=False,
                error="Invalid state: missing question/query",
            )

        question = self.get_question(state)
        execution_path: list[str] = ["classify"]

        # Classify the query
        route_name = await self.classify(question)
        execution_path.append(f"route:{route_name}")

        # Update state with route info
        current_state = dict(state)
        current_state["route"] = route_name

        # Get handler
        handler = self._routes.get(route_name)
        if handler is None:
            handler = self._routes.get(self._default_route)

        if handler is None:
            return self.create_result(
                current_state,
                success=False,
                error=f"No handler found for route: {route_name}",
                execution_path=execution_path,
            )

        # Execute handler
        try:
            logger.debug("Routing to handler: %s", handler.name)
            current_state = await handler.execute(current_state)
            execution_path.append(handler.name)

            return self.create_result(
                current_state,
                success=True,
                execution_path=execution_path,
                metadata={"route": route_name},
            )

        except Exception as e:
            logger.error("Handler %s failed: %s", handler.name, e)
            return self.create_result(
                current_state,
                success=False,
                error=str(e),
                execution_path=execution_path,
            )


def create_llm_classifier(
    llm: Any,
    routes: dict[str, str],
    default: str = "general",
) -> Callable[[str], Awaitable[str]]:
    """
    Create an LLM-based query classifier.

    Args:
        llm: LangChain LLM instance
        routes: Dict of route_name -> description
        default: Default route

    Returns:
        Classifier function
    """
    route_descriptions = "\n".join(
        f"- {name}: {desc}" for name, desc in routes.items()
    )

    prompt_template = f"""Classify the following query into one of these categories:

{route_descriptions}

Query: {{query}}

Respond with ONLY the category name, nothing else."""

    async def classifier(query: str) -> str:
        try:
            prompt = prompt_template.format(query=query)
            response = await llm.ainvoke(prompt)
            result = response.content.strip().lower() if hasattr(response, 'content') else str(response).strip().lower()

            # Match against known routes
            for route in routes:
                if route.lower() in result:
                    return route

            return default
        except Exception:
            return default

    return classifier
