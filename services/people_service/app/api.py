from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api")


class RunSimulationRequest(BaseModel):
    people_count: int = 100
    days: int = 0


@router.post("/simulation/run")
def run_simulation(payload: RunSimulationRequest, request: Request) -> dict:
    orchestrator = request.app.state.orchestrator
    orchestrator.initialize(payload.people_count)
    if payload.days > 0:
        orchestrator.run_days(payload.days)
    return {"status": "completed", "summary": orchestrator.summary()}


@router.get("/simulation/status")
def simulation_status(request: Request) -> dict:
    return request.app.state.orchestrator.summary()


@router.get("/people")
def list_people(request: Request) -> dict:
    people = request.app.state.orchestrator.people()
    return {
        "count": len(people),
        "people": [
            {
                "person_id": str(person.person_id),
                "name": person.name,
                "age": person.age,
                "salary": str(person.salary),
                "salary_deposit_day": person.salary_deposit_day,
                "spending_profile_category": person.spending_profile_category,
            }
            for person in people
        ],
    }


@router.get("/people/{person_id}")
def get_person(person_id: UUID, request: Request) -> dict:
    orchestrator = request.app.state.orchestrator
    person = orchestrator.person_by_id(person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    return {
        "person_id": str(person.person_id),
        "name": person.name,
        "age": person.age,
        "salary": str(person.salary),
        "salary_deposit_day": person.salary_deposit_day,
        "spending_profile_category": person.spending_profile_category,
        "current_balance": str(orchestrator.balance_of(person.primary_account_id)),
    }


@router.get("/merchants")
def list_merchants(request: Request) -> dict:
    merchants = request.app.state.orchestrator.merchants()
    return {
        "count": len(merchants),
        "merchants": [
            {
                "merchant_id": str(merchant.merchant_id),
                "name": merchant.name,
                "merchant_type": merchant.merchant_type,
            }
            for merchant in merchants
        ],
    }
