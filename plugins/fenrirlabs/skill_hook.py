# -*- coding: utf-8 -*-
"""Location: ./plugins/fenrirlabs/skill_hook.py
SPDX-License-Identifier: Apache-2.0

Fenrir Labs skill hook — thin native cpex adapter.

Configured once per skill via ``config.skill_id``. Delegates matching and SKILL.md loading
to the out-of-process fenrirlabs gateway service.
"""

from plugins.fenrirlabs.fenrirlabs_common import FenrirSkillAdapter


class FenrirSkillHook(FenrirSkillAdapter):
    """Inject Fenrir Labs skill context on tool_pre_invoke and prompt_pre_fetch."""
