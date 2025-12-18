from dotenv import load_dotenv

from planner import Planner

load_dotenv()

planner = Planner()
plan = planner.create_plan("напиши пост в вк")
print(plan.model_dump_json(indent=2, ensure_ascii=False))
