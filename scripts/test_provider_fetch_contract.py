from hdt_a2a.provider_a2a_client import fetch_contract_bundle

if __name__ == "__main__":
    b = fetch_contract_bundle(
        provider_url="http://localhost:9100/",
        algo_id="provider.riskScore",
        algo_version="1.2.0",
    )
    print("OK:", b["expected_contract_hash"])
