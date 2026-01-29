from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from .models import get_db, IgnoreList

router = APIRouter()

class IgnoreItem(BaseModel):
    value: str
    type: str # 'email' or 'domain'

class ImportRequest(BaseModel):
    items: list[IgnoreItem]


@router.get("/settings/ignore")
def get_ignore_list(db: Session = Depends(get_db)):
    items = db.query(IgnoreList).order_by(IgnoreList.created_at.desc()).all()
    return [{"id": item.id, "value": item.value, "type": item.type} for item in items]

@router.post("/settings/ignore")
def add_ignore_item(item: IgnoreItem, db: Session = Depends(get_db)):
    # Check duplicate
    existing = db.query(IgnoreList).filter(IgnoreList.value == item.value).first()
    if existing:
        raise HTTPException(status_code=400, detail="Item already exists")
    
    new_item = IgnoreList(value=item.value, type=item.type)
    db.add(new_item)
    db.commit()
    db.refresh(new_item)
    return {"id": new_item.id, "value": new_item.value, "type": new_item.type}

@router.delete("/settings/ignore/{item_id}")
def delete_ignore_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(IgnoreList).filter(IgnoreList.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    db.delete(item)
    db.commit()
    return {"status": "deleted"}

@router.post("/settings/ignore/import")
def import_ignore_items(req: ImportRequest, db: Session = Depends(get_db)):
    added_count = 0
    skipped_count = 0
    
    # Get all existing values to avoid individual DB checks if possible, or check one by one
    # For simplicity/safety, check one by one or getting all might be fine if list is small.
    # Let's check individually for now or use ON CONFLICT DO NOTHING if using core SQL.
    # ORM way:
    
    for item in req.items:
        existing = db.query(IgnoreList).filter(IgnoreList.value == item.value).first()
        if existing:
            skipped_count += 1
            continue
            
        new_item = IgnoreList(value=item.value, type=item.type)
        db.add(new_item)
        added_count += 1
    
    db.commit()
    return {"added": added_count, "skipped": skipped_count}

