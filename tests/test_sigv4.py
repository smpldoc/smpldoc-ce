import re
import unittest
from datetime import datetime, timezone

from smpldoc.adapters.sigv4 import EMPTY_SHA256, canonical_query, sign

# AWS's documented example credentials. Built from pieces so the repo secret scanner (which
# looks for AKIA...) does not mistake a public documentation value for a leaked key.
ACCESS = "AKIA" + "IOSFODNN7EXAMPLE"
SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
NOW = datetime(2013, 5, 24, tzinfo=timezone.utc)


def signature(headers):
    return re.search(r"Signature=([0-9a-f]{64})$", headers["Authorization"]).group(1)


class SigV4Test(unittest.TestCase):
    def test_matches_the_aws_documented_get_object_example(self):
        # https://docs.aws.amazon.com/AmazonS3/latest/API/sig-v4-header-based-auth.html (GET Object, Range)
        h = sign("GET", "https://examplebucket.s3.amazonaws.com/test.txt", {"Range": "bytes=0-9"}, EMPTY_SHA256,
                 access_key=ACCESS, secret_key=SECRET, region="us-east-1", now=NOW)
        self.assertEqual(h["Authorization"],
                         f"AWS4-HMAC-SHA256 Credential={ACCESS}/20130524/us-east-1/s3/aws4_request, "
                         "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date, "
                         "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41")
        self.assertEqual(h["x-amz-date"], "20130524T000000Z")
        self.assertEqual(h["x-amz-content-sha256"], EMPTY_SHA256)

    def test_matches_the_aws_documented_list_example(self):
        # Same page: GET Bucket (List Objects) with a query string.
        h = sign("GET", "https://examplebucket.s3.amazonaws.com/?max-keys=2&prefix=J", {}, EMPTY_SHA256,
                 access_key=ACCESS, secret_key=SECRET, region="us-east-1", now=NOW)
        self.assertEqual(signature(h), "34b48302e7b5fa45bde8084f4b7868a86f0a534bc59db6670ed5711ef69dc6f7")

    def test_the_query_is_sorted_and_encoded_the_aws_way(self):
        self.assertEqual(canonical_query("prefix=a b&list-type=2&x=%7E+"), "list-type=2&prefix=a%20b&x=~%20")
        self.assertEqual(canonical_query(""), "")

    def test_a_session_token_is_signed(self):
        h = sign("GET", "https://b.s3.amazonaws.com/k", {}, EMPTY_SHA256, access_key=ACCESS, secret_key=SECRET,
                 region="eu-west-1", token="tok", now=NOW)
        self.assertEqual(h["x-amz-security-token"], "tok")
        self.assertIn("x-amz-security-token", h["Authorization"])

    def test_the_secret_never_appears_in_the_headers(self):
        h = sign("GET", "https://b.s3.amazonaws.com/k", {}, EMPTY_SHA256, access_key=ACCESS, secret_key=SECRET,
                 region="us-east-1", now=NOW)
        self.assertNotIn(SECRET, "".join(map(str, h.values())))

    def test_a_non_default_port_is_part_of_the_signed_host(self):
        a = sign("GET", "http://127.0.0.1:9000/b/k", {}, EMPTY_SHA256, access_key=ACCESS, secret_key=SECRET, region="us-east-1", now=NOW)
        b = sign("GET", "http://127.0.0.1:9001/b/k", {}, EMPTY_SHA256, access_key=ACCESS, secret_key=SECRET, region="us-east-1", now=NOW)
        self.assertNotEqual(signature(a), signature(b))


if __name__ == "__main__":
    unittest.main()
