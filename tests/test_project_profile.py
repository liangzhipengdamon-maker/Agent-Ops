import unittest
import json
import os
import jsonschema

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "schemas", "project_profile.schema.json")
PROFILES_DIR = os.path.join(os.path.dirname(__file__), "..", "profiles")

def load_schema():
    with open(SCHEMA_PATH, "r") as f:
        return json.load(f)

def test_project_profiles_valid():
    schema = load_schema()
    for profile_file in os.listdir(PROFILES_DIR):
        if not profile_file.endswith(".json"):
            continue
        profile_path = os.path.join(PROFILES_DIR, profile_file)
        with open(profile_path, "r") as f:
            profile_data = json.load(f)
            
        jsonschema.validate(instance=profile_data, schema=schema)

class TestProjectProfileSchema(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema()
        self.valid_profile = {
            "project_identity": "test",
            "github": {"repository": "test/repo", "canonical_branch": "main"},
            "linear": {"team_key": "TEST", "project_id": "test-id"},
            "local_builder": {"relative_path": ".", "required_env_vars": []},
            "validation": {"ci_command": "true"},
            "reviewer_relay": {"binding_type": "test", "contact_uri": "test://uri"},
            "governance": {
                "capabilities": ["independent_review"],
                "required_gates": ["WAITING_PO_AUTH"],
                "protected_project": False,
                "cross_project_allowed": False
            }
        }

    def test_valid_profile_passes(self):
        jsonschema.validate(instance=self.valid_profile, schema=self.schema)

    def test_unknown_root_field(self):
        profile = dict(self.valid_profile)
        profile["unknown_field"] = "value"
        with self.assertRaises(jsonschema.exceptions.ValidationError):
            jsonschema.validate(instance=profile, schema=self.schema)

    def test_unknown_governance_field(self):
        profile = dict(self.valid_profile)
        profile["governance"] = dict(profile["governance"])
        profile["governance"]["unknown"] = "value"
        with self.assertRaises(jsonschema.exceptions.ValidationError):
            jsonschema.validate(instance=profile, schema=self.schema)

    def test_authority_looking_capability(self):
        profile = dict(self.valid_profile)
        profile["governance"] = dict(profile["governance"])
        profile["governance"]["capabilities"] = ["deploy_authorized"]
        with self.assertRaises(jsonschema.exceptions.ValidationError):
            jsonschema.validate(instance=profile, schema=self.schema)

    def test_unsupported_required_gate(self):
        profile = dict(self.valid_profile)
        profile["governance"] = dict(profile["governance"])
        profile["governance"]["required_gates"] = ["CUSTOM_GATE"]
        with self.assertRaises(jsonschema.exceptions.ValidationError):
            jsonschema.validate(instance=profile, schema=self.schema)

if __name__ == '__main__':
    unittest.main()
