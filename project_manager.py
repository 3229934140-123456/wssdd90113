import json
import os
import uuid
from datetime import datetime
from typing import List, Optional, Dict

from models import (
    ResearchProject, QueryParams, FollowUpRecord,
    MeetingMinutes, BatchComparisonResult
)


DEFAULT_PROJECTS_DIR = "./projects"


class ProjectManager:
    def __init__(self, projects_dir: str = DEFAULT_PROJECTS_DIR):
        self.projects_dir = projects_dir
        os.makedirs(self.projects_dir, exist_ok=True)

    def _project_path(self, project_id: str) -> str:
        return os.path.join(self.projects_dir, f"{project_id}.json")

    def _serialize_project(self, p: ResearchProject) -> Dict:
        params = p.query_params
        tr = None
        if params.time_range:
            tr = {
                "start": params.time_range.start_date.isoformat(),
                "end": params.time_range.end_date.isoformat(),
            }
        return {
            "project_id": p.project_id,
            "name": p.name,
            "query_params": {
                "target_brand": params.target_brand,
                "competing_brands": params.competing_brands,
                "time_range": tr,
                "focus_themes": params.focus_themes,
                "data_sources": params.data_sources,
            },
            "created_at": p.created_at.isoformat(),
            "updated_at": p.updated_at.isoformat(),
            "latest_analysis_ref": p.latest_analysis_ref,
            "exported_minutes_paths": p.exported_minutes_paths,
            "exported_comparison_paths": p.exported_comparison_paths,
            "follow_up_history": [
                {
                    "query": f.query,
                    "matched_keyword": f.matched_keyword,
                    "total_mentions": f.total_mentions,
                    "created_at": f.created_at.isoformat(),
                }
                for f in p.follow_up_history
            ],
            "notes": p.notes,
        }

    def _deserialize_project(self, data: Dict) -> ResearchProject:
        qp = data["query_params"]
        tr = None
        if qp.get("time_range"):
            tr_data = qp["time_range"]
            from models import TimeRange
            tr = TimeRange(
                start_date=datetime.fromisoformat(tr_data["start"]),
                end_date=datetime.fromisoformat(tr_data["end"]),
            )
        params = QueryParams(
            target_brand=qp["target_brand"],
            competing_brands=list(qp.get("competing_brands", [])),
            time_range=tr,
            focus_themes=list(qp.get("focus_themes", [])),
            data_sources=list(qp.get("data_sources", [])),
        )
        follow_ups = [
            FollowUpRecord(
                query=f["query"],
                matched_keyword=f["matched_keyword"],
                total_mentions=f["total_mentions"],
                created_at=datetime.fromisoformat(f["created_at"]),
            )
            for f in data.get("follow_up_history", [])
        ]
        return ResearchProject(
            project_id=data["project_id"],
            name=data["name"],
            query_params=params,
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            latest_analysis_ref=data.get("latest_analysis_ref", ""),
            exported_minutes_paths=list(data.get("exported_minutes_paths", [])),
            exported_comparison_paths=list(data.get("exported_comparison_paths", [])),
            follow_up_history=follow_ups,
            notes=data.get("notes", ""),
        )

    def create_project(
        self,
        name: str,
        params: QueryParams,
    ) -> ResearchProject:
        project_id = uuid.uuid4().hex[:10]
        project = ResearchProject(
            project_id=project_id,
            name=name.strip(),
            query_params=params,
        )
        self.save_project(project)
        return project

    def save_project(self, project: ResearchProject) -> None:
        project.updated_at = datetime.now()
        path = self._project_path(project.project_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._serialize_project(project), f, ensure_ascii=False, indent=2)

    def load_project(self, project_id: str) -> Optional[ResearchProject]:
        path = self._project_path(project_id)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return self._deserialize_project(data)

    def list_projects(self) -> List[ResearchProject]:
        projects: List[ResearchProject] = []
        for fname in os.listdir(self.projects_dir):
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.projects_dir, fname), "r", encoding="utf-8") as f:
                    data = json.load(f)
                projects.append(self._deserialize_project(data))
            except Exception:
                continue
        projects.sort(key=lambda p: p.updated_at, reverse=True)
        return projects

    def delete_project(self, project_id: str) -> bool:
        path = self._project_path(project_id)
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    def add_follow_up(
        self,
        project: ResearchProject,
        query: str,
        matched_keyword: str,
        total_mentions: int,
    ) -> None:
        project.follow_up_history.append(FollowUpRecord(
            query=query,
            matched_keyword=matched_keyword,
            total_mentions=total_mentions,
        ))
        self.save_project(project)

    def add_exported_minutes(self, project: ResearchProject, file_path: str) -> None:
        if file_path not in project.exported_minutes_paths:
            project.exported_minutes_paths.append(file_path)
            self.save_project(project)

    def add_exported_comparison(self, project: ResearchProject, file_path: str) -> None:
        if file_path not in project.exported_comparison_paths:
            project.exported_comparison_paths.append(file_path)
            self.save_project(project)

    def set_analysis_ref(self, project: ResearchProject, ref: str) -> None:
        project.latest_analysis_ref = ref
        self.save_project(project)


_global_pm: Optional[ProjectManager] = None


def get_project_manager(projects_dir: str = DEFAULT_PROJECTS_DIR) -> ProjectManager:
    global _global_pm
    if _global_pm is None:
        _global_pm = ProjectManager(projects_dir=projects_dir)
    return _global_pm
