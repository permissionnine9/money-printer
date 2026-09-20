"""素材池装配（从分镜 agents 层迁入）

- 素材池 ID 解析（lookbook_lb_* 定妆照 / mat_* 分集素材图）
- 素材池列表（定妆照 story 级 + 按集分组素材，不跨 story）
- 上传参考图路径校验（拒绝越出 static/uploads 的路径穿越）
"""
from backend.core.errors import WorkflowError
from backend.core.persistence.script_manager import ScriptManager
from backend.core.persistence.workspace_store import WorkspaceStore
from backend.core.services.workspace_sections import episode_number
from backend.core.utils.path_utils import resolve_project_path


class MaterialPoolService:
    """素材池读取与校验"""

    def __init__(
        self,
        store: WorkspaceStore,
        scm: ScriptManager,
        error_cls: type[WorkflowError] = WorkflowError,
    ):
        self.store = store
        self.scm = scm
        self.error = error_cls

    def resolve_pool_image(self, script_session_id: str, image_id: str) -> dict:
        """解析素材池 ID → {image_id, image_path, description}；不存在/跨 story/未完成抛业务异常

        ID 规则：lookbook_lb_* 定妆照（script_context.fetch_lookbook_images 的形态）/ mat_* 分集素材图
        """
        if image_id.startswith("lookbook_"):
            row = self.scm.get_lookbook(image_id[len("lookbook_"):])
        else:
            row = self.scm.get_episode_material(image_id)
        if not row or row.get("script_session_id") != script_session_id:
            raise self.error(f"素材图不存在或不属于当前剧本: {image_id}")
        if not row.get("image_path"):
            raise self.error(f"素材图尚未生成完成: {image_id}")
        return {
            "image_id": image_id,
            "image_path": row["image_path"],
            "description": row.get("description", ""),
        }

    def list_pool(self, script_session_id: str, episode_id: str) -> dict:
        """选择弹窗素材池：定妆照（story 级）+ 本集素材 + 其他集素材（不跨 story）"""
        groups = []
        lookbook = [
            {"image_id": m["image_id"], "image_path": m["image_path"], "description": m["description"]}
            for m in self._fetch_lookbook_images(script_session_id)
        ]
        if lookbook:
            groups.append({"key": "lookbook", "label": "核心素材", "materials": lookbook})

        episode_titles = {e["episode_id"]: (e.get("title") or "") for e in self.store.list_episodes(script_session_id)}
        by_episode: dict[str, list[dict]] = {}
        for row in self.scm.list_episode_materials(script_session_id, task_status="completed"):
            if not row.get("image_path"):
                continue
            by_episode.setdefault(row["episode_id"], []).append({
                "image_id": row["image_id"],
                "image_path": row["image_path"],
                "description": row.get("description", ""),
                "title": row.get("title", ""),
            })
        for eid in sorted(by_episode, key=episode_number):
            label = f"本集素材（{eid}《{episode_titles.get(eid, '')}》）" if eid == episode_id \
                else f"{eid}《{episode_titles.get(eid, '')}》素材"
            groups.append({
                "key": "current" if eid == episode_id else f"episode_{eid}",
                "label": label,
                "episode_id": eid,
                "materials": by_episode[eid],
            })
        return {"groups": groups}

    def _fetch_lookbook_images(self, script_session_id: str) -> list[dict]:
        """取已完成的定妆照（素材池形态，image_id 带 lookbook_ 前缀）"""
        return [
            {
                "image_id": f"lookbook_{row['image_id']}",
                "image_path": row["image_path"],
                "description": row["description"],
            }
            for row in self.scm.list_lookbook(script_session_id, task_status="completed")
            if row.get("image_path")
        ]

    def delete_material(self, script_session_id: str, image_id: str) -> bool:
        """删除分集素材图：DB 记录 + 本地归档文件（http 外链无文件可删）

        素材池分镜文件中的引用不在清理范围（与定妆照删除行为一致）。
        """
        row = self.scm.get_episode_material(image_id)
        if not row or row.get("script_session_id") != script_session_id:
            raise self.error(f"素材图不存在或不属于当前剧本: {image_id}", status_code=404)
        ok = self.scm.delete_episode_material(script_session_id, image_id)
        image_path = row.get("image_path") or ""
        if ok and image_path and not image_path.startswith(("http://", "https://")):
            try:
                resolve_project_path(image_path).unlink(missing_ok=True)
            except OSError:
                pass  # 文件清理失败不阻断记录删除
        return ok

    def validate_reference_paths(self, reference_paths: list[str]) -> list[str]:
        """上传参考图路径校验：resolve 后必须仍在 static/uploads 目录内（拒绝 ../.. 路径穿越）"""
        uploads_root = resolve_project_path("static/uploads").resolve()
        for path in reference_paths:
            resolved = resolve_project_path(path).resolve()
            if uploads_root != resolved.parent and uploads_root not in resolved.parents:
                raise self.error(f"非法的参考图路径: {path}")
            if not resolved.is_file():
                raise self.error(f"参考图文件不存在: {path}")
        return reference_paths
