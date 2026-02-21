"""
Jarvis v2 Trainer
Enhanced feedback, skill management, and improvement analysis.
"""

import json
from typing import Dict, Optional
from memory.memory import (
    add_feedback, get_feedback_summary, get_tool_run_stats,
    add_skill, get_skills, record_skill_use, get_memory_stats,
    get_all_preferences, DEFAULT_USER
)


class Trainer:
    """Manages learning from user feedback and building the skills library."""

    def rate(self, conversation_id: str, rating: int,
             message_id: str = None, tool_run_id: str = None,
             correction: str = None, label: str = None) -> Dict:
        if rating < 1 or rating > 5:
            return {"success": False, "error": "Rating must be 1-5"}
        fb_id = add_feedback(
            conversation_id=conversation_id,
            rating=rating,
            message_id=message_id,
            tool_run_id=tool_run_id,
            correction_text=correction,
            label=label,
        )
        return {"success": True, "feedback_id": fb_id, "message": f"Feedback recorded: {'⭐' * rating}"}

    def stats(self) -> Dict:
        tool_stats = get_tool_run_stats()
        fb_summary = get_feedback_summary()
        mem_stats = get_memory_stats()
        skills = get_skills()

        # Vector store stats
        vec_stats = {"available": False}
        try:
            from memory.vectors import VectorStore
            vs = VectorStore()
            vec_stats = vs.stats()
        except Exception:
            pass

        return {
            "tools": tool_stats,
            "feedback": fb_summary,
            "memory": mem_stats,
            "vectors": vec_stats,
            "skills_count": len(skills),
            "top_skills": sorted(
                [{"name": s["name"], "success_rate": s["success_rate"],
                  "times_used": s["times_used"]}
                 for s in skills],
                key=lambda x: x["times_used"],
                reverse=True
            )[:5]
        }

    def learn_skill(self, name: str, description: str, steps_json: str,
                    trigger_examples: str = None) -> Dict:
        skill_id = add_skill(name, description, steps_json, trigger_examples)
        return {"success": True, "skill_id": skill_id, "message": f"Skill '{name}' learned!"}

    def record_outcome(self, skill_id: str, success: bool) -> Dict:
        record_skill_use(skill_id, success)
        return {"success": True, "message": f"Outcome recorded for skill {skill_id}"}

    def get_improvements(self) -> Dict:
        fb_summary = get_feedback_summary()
        tool_stats = get_tool_run_stats()

        suggestions = []

        # Feedback analysis
        if fb_summary["total_feedback"] > 5 and fb_summary["avg_rating"] < 3.0:
            suggestions.append("Overall satisfaction is below 3/5. Review recent corrections.")

        if fb_summary.get("by_label"):
            for label, count in fb_summary["by_label"].items():
                if count >= 3:
                    suggestions.append(f"'{label}' feedback occurred {count} times. Investigate pattern.")

        # Tool failure analysis
        for tool_name, data in tool_stats.get("by_tool", {}).items():
            if data["count"] > 0:
                fail_rate = 1 - (data["successes"] / data["count"])
                if fail_rate > 0.3 and data["count"] >= 3:
                    suggestions.append(
                        f"Tool '{tool_name}' fails {fail_rate:.0%} of the time "
                        f"({data['count'] - data['successes']}/{data['count']}). Check configuration."
                    )

        if not suggestions:
            suggestions.append("All systems nominal. No issues detected.")

        return {
            "avg_rating": fb_summary["avg_rating"],
            "total_feedback": fb_summary["total_feedback"],
            "tool_stats": tool_stats,
            "suggestions": suggestions
        }
