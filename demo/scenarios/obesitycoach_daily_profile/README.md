# Mapping Plan Negotiation Demo

This scenario demonstrates A2A-based MappingPlan negotiation for a provider-side obesity coaching contract.

## Storyline

A provider-side algorithm (`provider.obesityCoach`, version `0.1.0`) publishes a contract describing the input fields it needs.

The user side does **not** expose a finalized physical database schema yet. Instead, it exposes a **logical vault view** (`daily_profile`) through a frozen `vault_catalog.json`.

The negotiation goal is to synthesize a MappingPlan that safely maps the user’s logical columns into the provider contract fields.

## Demo inputs

- Provider contract: `provider.obesityCoach:0.1.0`
- Dataset: `vault_dataset_A`
- Table: `daily_profile`

Key available logical columns:

- `txn_id`
- `dob`
- `date`
- `steps`
- `calories_in`
- `water_ml`

## Expected negotiation result

The final MappingPlan should map these core contract fields:

- `/recordId` <= `txn_id`
- `/person/birthDate` <= `parse_date(dob)`
- `/day/date` <= `parse_date(date)`
- `/activity/steps` <= `steps`
- `/nutrition/caloriesIn` <= `calories_in`
- `/hydration/waterMl` <= `water_ml`

## How to run

Start the provider agent in one terminal:

```powershell
python -m hdt_provider_a2a.server