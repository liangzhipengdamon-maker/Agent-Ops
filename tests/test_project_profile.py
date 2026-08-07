import json
import os
import jsonschema

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "schemas", "project_profile.schema.json")
PROFILES_DIR = os.path.join(os.path.dirname(__file__), "..", "profiles")

def test_project_profiles_valid():
    with open(SCHEMA_PATH, "r") as f:
        schema = json.load(f)
        
    for profile_file in os.listdir(PROFILES_DIR):
        if not profile_file.endswith(".json"):
            continue
        profile_path = os.path.join(PROFILES_DIR, profile_file)
        with open(profile_path, "r") as f:
            profile_data = json.load(f)
            
        jsonschema.validate(instance=profile_data, schema=schema)
