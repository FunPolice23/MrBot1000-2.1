"""
gui/dialogue_tab.py — Persona-driven goal dialogue (v2.1).

Driver (big, 5060 Ti) and Navigator (small, 1660 Super) hold a goal-driven,
fluid working conversation through a lifecycle:

    discuss → discover → discuss → plan → discuss → action → discuss → monitor → (repeat)

Instead of the old behaviour where the two "brains" repeatedly asked a (non-existent)
human for profile details, each turn is framed as the ACTIVE PERSONA working the
ACTIVE GOAL through the current lifecycle phase. The personas come from
agents.personas (real identity/strengths/abilities/memory/guardrails), decoupled
from the legacy prompts/*.txt role files.

Controls
--------
- ▶ Auto-Step : run a bounded number of turns (default 10) automatically, stopping
                when the phase count is exhausted.
- 🔄 Live     : keep the two personas conversing through the lifecycle indefinitely
                until Stop.
- ⏭ Step      : run exactly one persona turn now.
- Goal field  : the objective the conversation works toward (also setable from the
                Collaboration tab).
- ? Help      : opens the in-app feature help dialog.

Inference runs on a background QThread so the GUI never blocks.
"""

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import (
    QWidget, QTextEdit, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QComboBox, QListWidget, QGroupBox,
)
import os


# Driver (big, Marcus Rivera) is the ambitious strategist; Navigator (small, Alex Vega) is the cautious checker.
DRIVER_COLOR = "#4fc3f7"    # blue  -> Driver (Marcus Rivera)
NAVIGATOR_COLOR = "#03dac6" # teal  -> Navigator (Alex Vega)
HUMAN_COLOR = "#ffb300"     # amber -> Human
SYS_COLOR = "#9e9e9e"


def _persona_name(speaker: str) -> str:
    """Map legacy/alias speaker keys to canonical persona display names."""
    s = (speaker or "").lower()
    if s in ("big", "big brain", "driver", "driver (big)", "marcus", "marcus rivera", "rivera"):
        return "Marcus Rivera"
    if s in ("small", "small brain", "navigator", "navigator (small)", "alex", "alex vega", "vega"):
        return "Alex Vega"
    if s == "human":
        return "Human"
    return speaker or "Marcus Rivera"


def _emoji(speaker: str) -> str:
    n = _persona_name(speaker)
    return {"Marcus Rivera": "🚀", "Alex Vega": "🧭", "Human": "👤"}.get(n, "💬")


def _color(speaker: str) -> str:
    n = _persona_name(speaker)
    return {"Marcus Rivera": DRIVER_COLOR, "Alex Vega": NAVIGATOR_COLOR,
            "Human": HUMAN_COLOR}.get(n, SYS_COLOR)


# The fluid goal lifecycle. Each phase is (phase_label, driver_turn_bool,
# instruction). driver_turn_bool=True means DRIVER speaks first in that phase;
# the persona system prompt is built from agents.personas.
# NOTE: lifecycle is designed to converge — after 4-6 turns max, the personas
# commit to ONE concrete action instead of looping on planning.
# The personas should disagree, joke, and be themselves — not just agree politely.
LIFECYCLE = [
    # 1. Driver opens with a specific direction — be bold, maybe reckless
    ("discuss",   True,
     "Open the working session: restate the goal crisply and propose ONE concrete "
     "first action. Name the platform, the gig type, and why it fits. Be bold — "
     "Alex will push back if you're being reckless. Do NOT interview the human."),
    # 2. Navigator vets the specific proposal — push back hard, disagree if needed
    ("discover",  False,
     "React to Marcus Rivera's specific proposal. Either APPROVE it with a concrete "
     "risk-mitigation step, or RED-FLAG exactly what is unsafe and name a better "
     "alternative. Push back if he's being reckless — he needs your skepticism. "
     "Be specific — cite platform, payout, and risk. End with "
     "'APPROVED' or 'BLOCKED: <reason>'."),
    # 3. Driver commits to the final action — accept the pushback if it was right
    ("plan",      True,
     "State the FINAL action you will take. If Alex Vega blocked your first idea "
     "and named a better one, adopt it. Output exactly: "
     "ACTION: <one sentence describing the concrete step> | "
     "PLATFORM: <name> | EXPECTED: <time to $ / outcome>."),
    # 4. Navigator gives a binary gate — be honest, approve if it's actually good
    ("discuss",   False,
     "Give a binary gate: 'APPROVED — proceed' or 'BLOCKED — <specific reason>'. "
     "If the plan is actually good, say so — don't block just to block. "
     "No more planning — this is the go/no-go decision."),
]


class DialogueTab(QWidget):
    """Goal-driven conversation between the Driver and Navigator personas."""

    # Emitted when a goal is entered here so the Collaboration tab can mirror it.
    goal_changed = Signal(str)

    def __init__(self, small_brain, big_brain, parent=None):
        super().__init__(parent)
        self.small_brain = small_brain  # Alex Vega (Navigator) model
        self.big_brain = big_brain      # Marcus Rivera (Driver) model
        self.conversation_history = []
        self.goal = ""
        self._phase_index = 0
        self.is_running = False
        self.live_running = False
        self._auto_steps_left = 0
        self._max_auto_steps = 10
        self.worker = None
        self.current_speaker = "Marcus Rivera"  # Marcus Rivera (Driver) opens the dialogue
        self.setup_ui()
        # Sync adapter models from GUI selection on init
        self._sync_adapter_models()

    def _sync_adapter_models(self):
        """Sync adapter models from the Providers_GPU tab if available."""
        # Try to get the main window's providers_gpu_tab
        main_window = self.parent()
        while main_window is not None and not hasattr(main_window, 'providers_gpu_tab'):
            main_window = main_window.parent()
        
        if main_window is None:
            return
        
        providers_tab = getattr(main_window, 'providers_gpu_tab', None)
        if providers_tab is None:
            return
        
        # Sync Small Brain (Alex Vega) model
        try:
            path = providers_tab._current_model_path(True)
            if path:
                model_name = os.path.basename(path)
                # Try to match against server-reported models
                try:
                    running, models = providers_tab.provider_checker.check_llama_server(
                        providers_tab._brain_port(True), timeout=2)
                    if running and models:
                        path_base = model_name.lower().replace('.gguf', '').replace('-gguf', '')
                        for m in models:
                            model_base = m.lower().replace('.gguf', '').replace('-gguf', '')
                            if path_base in model_base or model_base in path_base:
                                model_name = m
                                break
                except Exception:
                    pass
                self.small_brain.model = model_name
        except Exception:
            pass
        
        # Sync Big Brain (Marcus Rivera) model
        try:
            path = providers_tab._current_model_path(False)
            if path:
                model_name = os.path.basename(path)
                try:
                    running, models = providers_tab.provider_checker.check_llama_server(
                        providers_tab._brain_port(False), timeout=2)
                    if running and models:
                        path_base = model_name.lower().replace('.gguf', '').replace('-gguf', '')
                        for m in models:
                            model_base = m.lower().replace('.gguf', '').replace('-gguf', '')
                            if path_base in model_base or model_base in path_base:
                                model_name = m
                                break
                except Exception:
                    pass
                self.big_brain.model = model_name
        except Exception:
            pass

    def _create_collapsible_panel(self, title: str, widget: QListWidget, button_text: str = None, button_callback=None) -> QWidget:
        """Create a collapsible panel with a toggle button."""
        panel = QWidget()
        panel.setStyleSheet("background: #1a1a1a; border: 1px solid #333; border-radius: 6px;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        
        # Header with toggle button
        header = QHBoxLayout()
        toggle_btn = QPushButton("▼")
        toggle_btn.setFixedSize(20, 20)
        toggle_btn.setStyleSheet("border: none; font-size: 10px; color: #ffb300;")
        header.addWidget(toggle_btn)
        
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: bold; font-size: 11px; color: #ccc;")
        header.addWidget(title_label)
        header.addStretch()
        
        if button_text and button_callback:
            add_btn = QPushButton(button_text)
            add_btn.setStyleSheet("font-size: 10px; padding: 2px 6px;")
            add_btn.clicked.connect(button_callback)
            header.addWidget(add_btn)
        
        layout.addLayout(header)
        
        # Collapsible content
        widget.setStyleSheet("""
            QListWidget {
                background: #0a0a0a;
                border: 1px solid #333;
                border-radius: 4px;
                font-size: 11px;
                color: #e0e0e0;
            }
        """)
        widget.setMinimumHeight(60)
        widget.setMaximumHeight(200)
        layout.addWidget(widget)
        
        # Toggle visibility
        def toggle():
            widget.setVisible(not widget.isVisible())
            toggle_btn.setText("▶" if not widget.isVisible() else "▼")
        toggle_btn.clicked.connect(toggle)
        
        return panel

    # ── UI ──────────────────────────────────────────────────────────────
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = QLabel("🚀 Marcus Rivera ⇄ Alex Vega  ·  Goal-Driven Dialogue")
        header.setStyleSheet("font-size: 15px; font-weight: bold; color: #ffb300; padding: 6px;")
        layout.addWidget(header)

        # Goal row
        goal_row = QHBoxLayout()
        goal_row.addWidget(QLabel("🎯 Goal:"))
        self.goal_input = QLineEdit()
        self.goal_input.setPlaceholderText("e.g. Earn $500 this week — set the objective the two personas work toward")
        self.goal_input.returnPressed.connect(self._apply_goal)
        goal_row.addWidget(self.goal_input, stretch=1)
        self.set_goal_btn = QPushButton("Set Goal")
        self.set_goal_btn.clicked.connect(self._apply_goal)
        goal_row.addWidget(self.set_goal_btn)
        layout.addLayout(goal_row)

        # Phase indicator
        self.phase_label = QLabel("phase: — (set a goal to begin)")
        self.phase_label.setStyleSheet("font-size: 12px; color: #9e9e9e; padding: 2px;")
        layout.addWidget(self.phase_label)

        # Main content: Chat (large) + Collapsible Sidebar
        main_layout = QHBoxLayout()
        
        # Chat display (takes most space - stretch=4)
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setMinimumHeight(500)
        self.chat_display.setStyleSheet("""
            QTextEdit {
                background: #0a0a0a; color: #e0e0e0;
                border: 1px solid #ffb30044; border-radius: 8px;
                font-size: 13px; padding: 10px;
            }
        """)
        main_layout.addWidget(self.chat_display, stretch=4)

        # Sidebar (stretch=1) - collapsible panels
        sidebar_layout = QVBoxLayout()
        sidebar_layout.setSpacing(4)
        
        # Create lists first
        self.tasks_list = QListWidget()
        self.progress_list = QListWidget()
        self.goals_list = QListWidget()
        
        # Create collapsible panels
        self.tasks_panel = self._create_collapsible_panel("📋 Tasks", self.tasks_list, "+ Add Task", self._add_task)
        sidebar_layout.addWidget(self.tasks_panel)
        
        self.progress_panel = self._create_collapsible_panel("📈 Progress", self.progress_list, None, None)
        sidebar_layout.addWidget(self.progress_panel)
        
        self.goals_panel = self._create_collapsible_panel("🎯 Goals", self.goals_list, None, None)
        sidebar_layout.addWidget(self.goals_panel)
        
        sidebar_layout.addStretch()
        main_layout.addLayout(sidebar_layout, stretch=1)
        
        layout.addLayout(main_layout, stretch=1)

        # Controls
        controls = QHBoxLayout()
        self.auto_btn = QPushButton("▶ Auto-Step")
        self.auto_btn.setToolTip("Run up to 10 persona turns automatically.")
        self.auto_btn.clicked.connect(self.auto_step)
        controls.addWidget(self.auto_btn)

        self.live_btn = QPushButton("🔁 Live")
        self.live_btn.setToolTip("Run a continuous Driver <-> Navigator goal dialogue until you Stop it.")
        self.live_btn.clicked.connect(self._toggle_live)
        controls.addWidget(self.live_btn)

        self.step_btn = QPushButton("⏭ Step")
        self.step_btn.setToolTip("Run exactly one persona turn now.")
        self.step_btn.clicked.connect(self.single_step)
        controls.addWidget(self.step_btn)

        self.reset_btn = QPushButton("🧹 Reset")
        self.reset_btn.clicked.connect(self.reset_dialogue)
        controls.addWidget(self.reset_btn)

        self.help_btn = QPushButton("❓ Help")
        self.help_btn.setToolTip("Open the in-app feature help.")
        self.help_btn.clicked.connect(self._open_help)
        controls.addWidget(self.help_btn)

        controls.addStretch()

        controls.addWidget(QLabel("Start turn as:"))
        self.speaker_combo = QComboBox()
        self.speaker_combo.addItems(["Marcus Rivera", "Alex Vega"])
        self.speaker_combo.setFixedWidth(140)
        controls.addWidget(self.speaker_combo)
        layout.addLayout(controls)

        # Input area
        input_layout = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type a message or let Auto-Step / Live drive the goal...")
        self.input.returnPressed.connect(self.on_send)
        input_layout.addWidget(self.input)
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self.on_send)
        input_layout.addWidget(self.send_btn)
        layout.addLayout(input_layout)

    # ── goal + phase ────────────────────────────────────────────────────
    def set_goal(self, goal: str):
        """Set the active goal (used by the Dialogue + Collaboration wiring)."""
        goal = (goal or "").strip()
        if goal != self.goal:
            self.goal = goal
            self.goal_input.setText(goal)
            self.phase_label.setText(f"phase: — (goal set · press ▶ Auto-Step or 🔁 Live)")
            self.goal_changed.emit(goal)

    def _apply_goal(self):
        goal = self.goal_input.text().strip()
        if not goal:
            return
        self.goal = goal
        self.phase_label.setText("phase: — (goal set · press ▶ Auto-Step or 🔁 Live)")
        self.goal_changed.emit(goal)
        self.append_system(f"🎯 Goal set: {goal}")

    def _next_phase(self) -> tuple:
        """Advance to the next lifecycle phase and return its tuple."""
        phase = LIFECYCLE[self._phase_index % len(LIFECYCLE)]
        self._phase_index += 1
        return phase

    def _current_phase_speaker(self) -> str:
        """The persona that should speak for the next autonomous turn.

        Advances the lifecycle index so Driver and Navigator alternate as each
        phase is consumed.
        """
        phase = self._next_phase()
        return "Driver" if phase[1] else "Navigator"

    def _phase_instruction(self) -> str:
        # Instruction of the phase most recently consumed by _current_phase_speaker.
        idx = (self._phase_index - 1) % len(LIFECYCLE)
        return LIFECYCLE[idx][2]

    # ── actions ─────────────────────────────────────────────────────────
    def on_send(self):
        msg = self.input.text().strip()
        if not msg:
            return
        speaker = _persona_name(self.speaker_combo.currentText())
        self._append(speaker, msg)
        self.conversation_history.append({"role": "assistant", "content": msg, "speaker": speaker})
        self.input.clear()
        # The other persona responds.
        self.current_speaker = "Alex Vega" if speaker == "Marcus Rivera" else "Marcus Rivera"
        self.respond()

    def respond(self):
        """Generate a response from the current speaker on a background thread.

        No-op if a response is already in flight (never stacks overlapping
        inference threads).
        """
        if getattr(self, "worker", None) is not None and self.worker.isRunning():
            return

        # Sync adapter models from GUI selection before responding
        self._sync_adapter_models()

        # Use the unified context that blends casual + goal-driven conversation
        self.current_speaker = _persona_name(self.current_speaker)

        from agents.personas import persona_for_key
        persona = persona_for_key(self.current_speaker)
        system_prompt = persona.build_system_prompt(goal=self.goal) if persona else None

        context = self.get_dialogue_context()
        brain = self.big_brain if self.current_speaker == "Marcus Rivera" else self.small_brain
        self.worker = DialogueWorker(brain, context, self.conversation_history,
                                     self.current_speaker, system_prompt)
        self.worker.finished.connect(self._on_response_ready)
        self.worker.start()

    def _on_response_ready(self, response: str, speaker: str):
        if not self.is_running and not self.live_running \
           and getattr(self, "_auto_steps_left", 0) == 0 \
           and not self.conversation_history:
            self.auto_btn.setText("▶ Auto-Step")
            return
        speaker = _persona_name(speaker)
        
        # Handle empty responses
        if not response or response.strip() == "(empty)" or response.strip() == "":
            response = f"[{speaker}: No response generated. The model may need a different prompt or context.]"
        
        self._append(speaker, response)
        self.conversation_history.append({"role": "assistant", "content": response, "speaker": speaker})
        self.worker = None

        # Toggle speaker for next turn
        self.current_speaker = "Alex Vega" if speaker == "Marcus Rivera" else "Marcus Rivera"

        # Decide whether to chain another turn.
        chained = False
        if self.is_running and getattr(self, "_auto_steps_left", 0) > 0:
            self._auto_steps_left -= 1
            if self._auto_steps_left > 0:
                chained = True
            else:
                self.is_running = False
                self.auto_btn.setText("▶ Auto-Step")
                self._phase_index = 0  # reset cycle for next Auto-Step run
        elif self.live_running:
            # Hard limit: stop after 100 exchanges to prevent infinite loops
            if len(self.conversation_history) >= 100:
                self.stop_live()
                self.append_system("🎯 Conversation ended (100 exchanges). Click Live to start a new one.")
            else:
                chained = True
        
        if chained:
            self.respond()

    def auto_step(self):
        """Run a bounded number of persona turns through the lifecycle."""
        self.live_running = False
        self.is_running = True
        self._auto_steps_left = self._max_auto_steps
        self.auto_btn.setText("⏸ Stop")
        if not self.conversation_history and self.goal:
            self.append_system(f"Starting a goal-driven pass on: {self.goal}")
            self._phase_index = 0
        self.respond()

    def live(self):
        """Run a continuous Driver<->Navigator dialogue until stopped."""
        self.live_running = True
        self.is_running = False
        self.live_btn.setText("⏸ Stop Live")
        if not self.conversation_history:
            if self.goal:
                self.append_system(f"Starting a continuous goal-driven pass on: {self.goal}")
            self._phase_index = 0
        self.respond()

    def stop_live(self):
        self.live_running = False
        self.is_running = False
        self._auto_steps_left = 0
        self.live_btn.setText("🔁 Live")
        self.auto_btn.setText("▶ Auto-Step")

    def _toggle_live(self):
        if self.live_running:
            self.stop_live()
        else:
            self.live()

    def single_step(self):
        """Run exactly one persona turn."""
        self.stop_live()
        self.is_running = False
        if not self.conversation_history and self.goal:
            self.append_system(f"Starting a goal-driven pass on: {self.goal}")
            self._phase_index = 0
        self.respond()

    def reset_dialogue(self):
        """Reset the conversation history and phase."""
        self.conversation_history.clear()
        self._phase_index = 0
        self.is_running = False
        self.live_running = False
        self._auto_steps_left = 0
        self.auto_btn.setText("▶ Auto-Step")
        self.live_btn.setText("🔁 Live")
        self.phase_label.setText("phase: — (set a goal to begin)")
        self.chat_display.clear()
        self.tasks_list.clear()
        self.progress_list.clear()
        self.goals_list.clear()

    def _open_help(self):
        """Open the in-app feature help dialog."""
        try:
            from gui.help_dialog import HelpDialog
            dlg = HelpDialog(self)
            dlg.exec()
        except Exception:
            pass

    def _add_task(self):
        """Add a task to the tasks list."""
        text, ok = QLineEdit().text(), False
        # Simple input dialog
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, "Add Task", "Task description:")
        if ok and text:
            self.tasks_list.addItem(f"- [ ] {text}")

    # ── sidebar helpers ─────────────────────────────────────────────────
    def _extract_tasks_from_message(self, message: str):
        """Extract task items from a message and add them to the tasks list."""
        import re
        # Find task patterns: - [ ] task or - [x] task
        tasks = re.findall(r'- \[([ xX])\] (.+?)(?:\n|$)', message)
        for done, task in tasks:
            item = f"- [{'x' if done.lower() == 'x' else ' '}] {task}"
            # Avoid duplicates
            existing = [self.tasks_list.item(i).text() for i in range(self.tasks_list.count())]
            if item not in existing:
                self.tasks_list.addItem(item)

    # ── context builder ─────────────────────────────────────────────────
    def get_dialogue_context(self) -> str:
        """Build context for the dialogue.
        
        v2.1: Minimal context. The old version was too long and the model
        ignored the tool instructions. Now it's short and focused.
        """
        if not self.conversation_history:
            if self.goal:
                return (
                    f"You are {self.current_speaker}. "
                    f"ACTIVE GOAL: {self.goal}\n"
                    f"Talk with {'Alex Vega' if self.current_speaker == 'Marcus Rivera' else 'Marcus Rivera'}. "
                    f"Use first person ('I', 'me', 'my'). "
                    f"When you need data, CALL A TOOL.\n"
                    f'web_search("query") web_read("url") web_check("url")\n'
                    f'workshop_proposal("Title","Client","Desc") run_command("cmd")'
                )
            return (
                f"You are {self.current_speaker}. "
                f"Talk with {'Alex Vega' if self.current_speaker == 'Marcus Rivera' else 'Marcus Rivera'}. "
                f"Use first person ('I', 'me', 'my'). "
                f"When you need data, CALL A TOOL.\n"
                f'web_search("query") web_read("url") web_check("url")'
            )
        
        # Build conversation summary
        total_msgs = len(self.conversation_history)
        if total_msgs > 6:
            old_msgs = self.conversation_history[:-6]
            recent_msgs = self.conversation_history[-6:]
            summary_parts = []
            for msg in old_msgs:
                speaker = msg.get("speaker", "?")
                content = msg.get("content", "")[:100]
                summary_parts.append(f"{speaker}: {content}")
            summary = "\n".join(summary_parts)
            recent_parts = []
            for msg in recent_msgs:
                speaker = msg.get("speaker", "?")
                content = msg.get("content", "")
                recent_parts.append(f"{speaker}: {content}")
            recent = "\n".join(recent_parts)
            history_block = (
                f"## CONVERSATION HISTORY (summary of first {len(old_msgs)} messages)\n"
                f"{summary}\n\n"
                f"## RECENT MESSAGES (last 6)\n{recent}"
            )
        else:
            parts = []
            for msg in self.conversation_history:
                speaker = msg.get("speaker", "?")
                content = msg.get("content", "")
                parts.append(f"{speaker}: {content}")
            history_block = "\n".join(parts)
        
        turn_count = len(self.conversation_history)
        
        # Anti-looping
        loop_prompt = ""
        if turn_count >= 4:
            recent_questions = []
            for msg in self.conversation_history[-3:]:
                content = msg.get("content", "")
                import re
                questions = re.findall(r'[^.!?]*\?', content)
                recent_questions.extend(questions)
            if len(recent_questions) >= 2:
                from collections import Counter
                counts = Counter(recent_questions)
                most_common = counts.most_common(1)[0]
                if most_common[1] >= 2:
                    loop_prompt = ("\n\n⚠️ LOOP DETECTED: You've been asking the same question repeatedly. "
                                 "BREAK THE LOOP. Make a decision right now. "
                                 "Pick an option, commit to it, and move forward. "
                                 "No more questions — take action.")
        
        closing_prompt = ""
        if turn_count >= 15:
            closing_prompt = (f"\n\nThis conversation has been going on for {turn_count} messages. "
                            f"Please bring it to a natural, satisfying conclusion in 1-2 sentences. "
                            f"End with a concrete action item or agreement on next steps.")
        
        goal_line = f"\n\nACTIVE GOAL: {self.goal}" if self.goal else ""
        
        return (
            f"You are {self.current_speaker}. "
            f"Talking with {'Alex Vega' if self.current_speaker == 'Marcus Rivera' else 'Marcus Rivera'}.{goal_line}\n\n"
            f"{history_block}\n\n"
            f"Respond AS {self.current_speaker} in first person ('I', 'me', 'my'). "
            f"When you need data, CALL A TOOL.\n"
            f'web_search("query") web_read("url") web_check("url")\n'
            f'workshop_proposal("Title","Client","Desc") run_command("cmd")\n'
            f"NEVER make up data. NEVER say 'I will search' without calling the tool.\n"
            f"{loop_prompt}"
            f"{closing_prompt}"
        )

    # ── display ─────────────────────────────────────────────────────────
    def append_system(self, text: str):
        self.chat_display.append(
            f'<i style="color:{SYS_COLOR};">{text}</i>')
        self.chat_display.verticalScrollBar().setValue(
            self.chat_display.verticalScrollBar().maximum())

    def _append(self, sender, message):
        name = _persona_name(sender)
        # Clean message: remove <br> tags, stage directions, and fake wins
        import re
        clean_msg = re.sub(r'<br\s*/?>', ' ', message)
        # Remove stage directions: (Marcus leans back...), (Alex sighs...), etc.
        clean_msg = re.sub(r'\s*\([^)]{10,}\)\s*', ' ', clean_msg)
        # Remove fake win claims
        clean_msg = re.sub(r'(we\s+(hit|secured|locked|earned|made|got|achieved|reached)\s+(the\s+)?[\$]?\d+[\w\s]*)', '', clean_msg, flags=re.IGNORECASE)
        # Remove fake completion claims
        clean_msg = re.sub(r'(the\s+[\$]?\d+\s+(is\s+)?(secured|locked|in|ours|achieved|done|complete|won))', '', clean_msg, flags=re.IGNORECASE)
        clean_msg = re.sub(r'\s+', ' ', clean_msg).strip()
        
        # Extract tasks from the message
        self._extract_tasks_from_message(clean_msg)
        
        # Convert markdown to HTML for display
        html_msg = self._markdown_to_html(clean_msg)
        
        self.chat_display.append(
            f'<b style="color:{_color(sender)};">{_emoji(sender)} {name}:</b>')
        self.chat_display.append(f'<p style="margin:4px 0 12px 0;">{html_msg}</p>')
        self.chat_display.verticalScrollBar().setValue(
            self.chat_display.verticalScrollBar().maximum())

    def _markdown_to_html(self, text: str) -> str:
        """Convert markdown to HTML for display in QTextEdit."""
        import re
        # Headers
        text = re.sub(r'^### (.+)$', r'<h3 style="color:#ffb300;margin:8px 0 4px 0;">\1</h3>', text, flags=re.MULTILINE)
        text = re.sub(r'^## (.+)$', r'<h2 style="color:#ffb300;margin:10px 0 6px 0;">\1</h2>', text, flags=re.MULTILINE)
        # Bold
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
        # Italic
        text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
        # Task lists: - [ ] or - [x]
        text = re.sub(r'- \[ \] (.+?)(\n|$)', r'☐ \1<br>', text)
        text = re.sub(r'- \[x\] (.+?)(\n|$)', r'☑ \1<br>', text)
        # Numbered lists
        text = re.sub(r'^(\d+)\. (.+?)$', r'\1. \2', text, flags=re.MULTILINE)
        # Line breaks
        text = text.replace('\n', '<br>')
        return text

    def _show_thoughts(self):
        """Show the thought panel (placeholder)."""
        pass


class DialogueWorker(QThread):
    """Background worker for dialogue inference (persona-driven)."""

    finished = Signal(str, str)  # response, speaker

    def __init__(self, brain, context, history, speaker, system_prompt=None):
        super().__init__()
        self.brain = brain
        self.context = context
        self.history = history
        self.speaker = speaker
        self.system_prompt = system_prompt

    def run(self):
        try:
            kwargs = {}
            if self.system_prompt:
                kwargs["system_prompt"] = self.system_prompt
            response = self.brain.chat(self.context, self.history, **kwargs)
            self.finished.emit(response or "(empty)", self.speaker)
        except Exception as e:
            self.finished.emit(f"Error: {str(e)}", self.speaker)
