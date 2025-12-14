"""
Prompt manager that loads templates from YAML/JSON files.
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from third_party.sag.exceptions import PromptError
from third_party.sag.utils import get_logger

logger = get_logger("prompt.manager")


class PromptTemplate:
    def __init__(
        self,
        name: str,
        template: str,
        variables: Optional[List[str]] = None,
        description: Optional[str] = None,
    ) -> None:
        self.name = name
        self.template = template
        self.variables = variables or []
        self.description = description

    def render(self, **kwargs: Any) -> str:
        missing = set(self.variables) - set(kwargs.keys())
        if missing:
            raise PromptError(f"Template '{self.name}' missing variables: {', '.join(missing)}")
        try:
            return self.template.format(**kwargs)
        except KeyError as e:
            raise PromptError(f"Template variable error: {e}") from e
        except Exception as e:
            raise PromptError(f"Template render failed: {e}") from e

    def validate_variables(self, **kwargs: Any) -> bool:
        missing = set(self.variables) - set(kwargs.keys())
        return len(missing) == 0


class PromptManager:
    def __init__(self, prompts_dir: Optional[Path] = None) -> None:
        if prompts_dir is None:
            current_file = Path(__file__)
            project_root = current_file.parent.parent.parent  # .../sag
            prompts_dir = project_root / "prompts"

        self.prompts_dir = Path(prompts_dir)
        self.templates: Dict[str, PromptTemplate] = {}

        if self.prompts_dir.exists():
            self.load_templates()
            logger.info(
                "Prompt manager initialized",
                extra={"prompts_dir": str(self.prompts_dir), "count": len(self.templates)},
            )
        else:
            logger.warning(f"Prompts directory not found: {self.prompts_dir}")

    def load_templates(self) -> None:
        if not self.prompts_dir.exists():
            logger.warning(f"Prompts directory not found: {self.prompts_dir}")
            return

        yaml_files = list(self.prompts_dir.glob("*.yaml")) + list(self.prompts_dir.glob("*.yml"))
        json_files = list(self.prompts_dir.glob("*.json"))

        for yaml_file in yaml_files:
            try:
                self._load_yaml_file(yaml_file)
            except Exception as e:
                logger.error(f"Failed to load prompt file {yaml_file}: {e}", exc_info=True)

        for json_file in json_files:
            try:
                self._load_json_file(json_file)
            except Exception as e:
                logger.error(f"Failed to load prompt file {json_file}: {e}", exc_info=True)

    def _load_yaml_file(self, yaml_file: Path) -> None:
        with open(yaml_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            logger.warning(f"Invalid YAML format: {yaml_file}")
            return
        for name, config in data.items():
            if not isinstance(config, dict):
                continue
            template_text = config.get("template", "")
            variables = config.get("variables", [])
            description = config.get("description", "")
            template = PromptTemplate(
                name=name,
                template=template_text,
                variables=variables,
                description=description,
            )
            self.templates[name] = template
            logger.debug(f"Loaded template: {name}")

    def _load_json_file(self, json_file: Path) -> None:
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            # allow a single template or a dict of templates
            if "template" in data:
                data = {json_file.stem: data}
        if not isinstance(data, dict):
            logger.warning(f"Invalid JSON format: {json_file}")
            return

        for name, config in data.items():
            if not isinstance(config, dict):
                continue
            template_text = config.get("template", "")
            variables = config.get("variables", [])
            description = config.get("description", "")
            template = PromptTemplate(
                name=name,
                template=template_text,
                variables=variables,
                description=description,
            )
            self.templates[name] = template
            logger.debug(f"Loaded template: {name}")

    def get(self, name: str) -> PromptTemplate:
        if name not in self.templates:
            raise PromptError(f"Template not found: {name}")
        return self.templates[name]

    def render(self, name: str, **kwargs: Any) -> str:
        template = self.get(name)
        return template.render(**kwargs)


_manager: Optional[PromptManager] = None


def get_prompt_manager(prompts_dir: Optional[Path] = None) -> PromptManager:
    global _manager
    if _manager is None:
        _manager = PromptManager(prompts_dir=prompts_dir)
    return _manager
