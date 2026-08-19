import unittest
import os
import sys
import json
import tempfile
import numpy as np
import pandas as pd
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from anomaly_detector import AnomalyDetector
from drift_detector import DataDriftDetector

class TestDirective27S3Baseline(unittest.TestCase):
    def setUp(self):
        self.detector = DataDriftDetector()
        self.detector.baselines = {
            "rps": np.array([100.0, 105.0, 98.0, 102.0, 101.0]),
            "latency_p90": np.array([0.05, 0.04, 0.06, 0.05, 0.05]),
            "cpu_usage": np.array([0.20, 0.22, 0.19, 0.21, 0.20])
        }

    def test_local_baseline_persistence(self):
        self.detector.current_version = "v1.2.3-test"
        self.detector.save_persisted_baseline()
        self.assertTrue(os.path.exists(self.detector.store_file))
        
        with open(self.detector.store_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertEqual(data["version"], "v1.2.3-test")
            self.assertIn("rps", data["metrics"])

    @patch("boto3.client")
    def test_upload_baseline_to_s3(self, mock_boto_client):
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3
        
        with patch.dict(os.environ, {"AWS_ACCESS_KEY_ID": "mock-key"}):
            success = self.detector.upload_baseline_to_s3(version_tag="v20260730-120000")
            self.assertTrue(success)
            self.assertEqual(self.detector.current_version, "v20260730-120000")
            mock_s3.upload_file.assert_called()
            mock_s3.put_object.assert_called()

    @patch("boto3.client")
    def test_check_and_reload_s3_baseline(self, mock_boto_client):
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3
        
        manifest_payload = json.dumps({
            "version": "v20260730-999999",
            "s3_key": "baselines/v20260730-999999/baseline_drift_store.json"
        }).encode("utf-8")
        
        mock_s3.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=manifest_payload))}
        
        def mock_download(bucket, key, filename):
            with open(filename, "w", encoding="utf-8") as f:
                json.dump({
                    "version": "v20260730-999999",
                    "metrics": {"rps": [200.0, 205.0, 198.0]}
                }, f)

        mock_s3.download_file.side_effect = mock_download
        
        with patch.dict(os.environ, {"AWS_ACCESS_KEY_ID": "mock-key"}):
            reloaded = self.detector.check_and_reload_s3_baseline(force=True)
            self.assertTrue(reloaded)
            self.assertEqual(self.detector.current_version, "v20260730-999999")
            self.assertIn("rps", self.detector.baselines)
            self.assertEqual(float(self.detector.baselines["rps"][0]), 200.0)

    @patch("anomaly_detector.joblib.load")
    @patch("anomaly_detector.boto3.client")
    def test_anomaly_detector_loads_manifest_with_irsa_web_identity_env(self, mock_boto_client, mock_joblib_load):
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3
        mock_joblib_load.return_value = object()

        manifest = {
            "validation_passed": True,
            "version": "v-irsa-test",
            "f1_score_average": 0.91,
            "model_paths": {
                "checkout": "models/current/checkout_iforest.joblib",
            },
        }

        with tempfile.TemporaryDirectory() as models_dir:
            token_path = os.path.join(models_dir, "web-identity-token")
            with open(token_path, "w", encoding="utf-8") as f:
                f.write("token")

            def fake_download_file(_bucket, key, filename):
                if key == "active_manifest.json":
                    with open(filename, "w", encoding="utf-8") as f:
                        json.dump(manifest, f)
                else:
                    with open(filename, "wb") as f:
                        f.write(b"model")

            mock_s3.download_file.side_effect = fake_download_file

            detector = object.__new__(AnomalyDetector)
            detector.s3_bucket = "tf3-aiops-models-197826770971"
            detector.models_dir = models_dir
            detector.iforest_models = {}
            detector.models = detector.iforest_models

            with patch.dict(
                os.environ,
                {
                    "AWS_ROLE_ARN": "arn:aws:iam::197826770971:role/techx-corp-tf3-aiops-engine",
                    "AWS_WEB_IDENTITY_TOKEN_FILE": token_path,
                    "AWS_DEFAULT_REGION": "ap-southeast-1",
                },
                clear=False,
            ):
                os.environ.pop("AWS_ACCESS_KEY_ID", None)
                detector._load_models_from_s3()

        mock_boto_client.assert_called_with("s3", region_name="ap-southeast-1")
        mock_s3.download_file.assert_any_call(
            "tf3-aiops-models-197826770971",
            "active_manifest.json",
            unittest.mock.ANY,
        )
        mock_s3.download_file.assert_any_call(
            "tf3-aiops-models-197826770971",
            "current/checkout_iforest.joblib",
            unittest.mock.ANY,
        )
        self.assertIn("checkout", detector.iforest_models)

    @patch("requests.get")
    def test_extract_baseline_from_prometheus(self, mock_requests_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": "success",
            "data": {
                "result": [
                    {
                        "values": [
                            [1700000000, "150.0"],
                            [1700000300, "152.0"],
                            [1700000600, "148.0"],
                            [1700000900, "151.0"],
                            [1700001200, "999.0"]  # Outlier 3-sigma to be filtered out
                        ]
                    }
                ]
            }
        }
        mock_requests_get.return_value = mock_response

        with patch.object(self.detector, "upload_baseline_to_s3", return_value=True):
            success = self.detector.extract_baseline_from_prometheus(lookback_hours=24)
            self.assertTrue(success)
            self.assertIn("rps", self.detector.baselines)

if __name__ == "__main__":
    unittest.main()
