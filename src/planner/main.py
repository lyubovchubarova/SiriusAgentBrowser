from dotenv import load_dotenv
from planner import Planner

load_dotenv()

planner = Planner()
plan = planner.create_plan("Найди статью про Python")
print(plan)
#print(plan.model_dump_json(indent=2, ensure_ascii=False))
