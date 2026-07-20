from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Task, User
from app.schemas import TaskCreate, TaskUpdate, TaskOut
from app.auth import get_current_user
from app.cache import cache_get, cache_set, cache_delete
from app.kafka_client import publish_event
from app.config import settings

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _list_cache_key(user_id: int) -> str:
    return f"tasks:user:{user_id}"


def _publish_task_event(background_tasks: BackgroundTasks, event_type: str, task: Task):
    """
    Publishes to Kafka in a background task, AFTER the response is sent.
    This is what makes it truly async from the client's perspective - the
    request doesn't wait on the network round-trip to the Kafka broker.
    """
    payload = {
        "event_type": event_type,          # "task.created" | "task.updated" | "task.deleted"
        "task_id": task.id,
        "owner_id": task.owner_id,
        "status": task.status.value if hasattr(task.status, "value") else task.status,
        "title": task.title,
    }
    background_tasks.add_task(publish_event, settings.kafka_tasks_topic, payload)


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(
    task_in: TaskCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = Task(**task_in.model_dump(), owner_id=current_user.id)
    db.add(task)
    db.commit()
    db.refresh(task)
    cache_delete(_list_cache_key(current_user.id))  # invalidate stale list
    _publish_task_event(background_tasks, "task.created", task)
    return task


@router.get("", response_model=list[TaskOut])
def list_tasks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    key = _list_cache_key(current_user.id)
    cached = cache_get(key)
    if cached is not None:
        return cached

    tasks = db.query(Task).filter(Task.owner_id == current_user.id).all()
    result = [TaskOut.model_validate(t).model_dump(mode="json") for t in tasks]
    cache_set(key, result)
    return tasks


@router.get("/{task_id}", response_model=TaskOut)
def get_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = db.query(Task).filter(Task.id == task_id, Task.owner_id == current_user.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(
    task_id: int,
    task_in: TaskUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = db.query(Task).filter(Task.id == task_id, Task.owner_id == current_user.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    for field, value in task_in.model_dump(exclude_unset=True).items():
        setattr(task, field, value)

    db.commit()
    db.refresh(task)
    cache_delete(_list_cache_key(current_user.id))
    _publish_task_event(background_tasks, "task.updated", task)
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(
    task_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = db.query(Task).filter(Task.id == task_id, Task.owner_id == current_user.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    _publish_task_event(background_tasks, "task.deleted", task)
    db.delete(task)
    db.commit()
    cache_delete(_list_cache_key(current_user.id))
    return None
