from algosdk.v2client import algod, indexer
import os
from dotenv import load_dotenv
import sys

def verify_algod_client():
    try:
        # Load environment variables
        load_dotenv()
        
        # Get Algorand node credentials from environment
        # algod_token = os.getenv("ALGOD_TOKEN")
        # algod_address = os.getenv("ALGOD_ADDRESS")

        algod_token = "t-6813fc5b5b3413c0dbfaadfa-a6ca655a5753484b84450adb"
        algod_address = "https://algorand-mainnet-algod.gateway.tatum.io/"
        
        # if not algod_token or not algod_address:
        #     return False, "Missing ALGOD_TOKEN or ALGOD_ADDRESS environment variables"
        
        # Initialize algod client
        algod_client = algod.AlgodClient(
            algod_token=algod_token,
            algod_address=algod_address,
            headers={
                'User-Agent': 'py-algorand-sdk',
                'x-algo-api-token': algod_token
            }
        )
        
        # Try to get node status
        status = algod_client.status()
        return True, f"Algod client is working. Last round: {status['last-round']}"
        
    except Exception as e:
        return False, f"Algod client error: {str(e)}"

def verify_indexer_client():
    try:
        # Get Indexer credentials from environment
        indexer_token = os.getenv("ALGOD_TOKEN")  # Project uses same token for both
        indexer_address = os.getenv("ALGO_INDEXER_ADDRESS")
        
        if not indexer_token or not indexer_address:
            return False, "Missing ALGOD_TOKEN or ALGO_INDEXER_ADDRESS environment variables"
        
        # Initialize indexer client
        indexer_client = indexer.IndexerClient(
            indexer_token=indexer_token,
            indexer_address=indexer_address,
            headers={
                'User-Agent': 'py-algorand-sdk',
                'x-algo-api-token': indexer_token
            }
        )
        
        # Try to get health status
        health = indexer_client.health()
        return True, "Indexer client is working. Health check passed."
        
    except Exception as e:
        return False, f"Indexer client error: {str(e)}"

def main():
    print("🔍 Verifying Algorand credentials...")
    print("\n1. Checking Algod client...")
    algod_success, algod_message = verify_algod_client()
    print(f"{'✅' if algod_success else '❌'} {algod_message}")
    
    print("\n2. Checking Indexer client...")
    indexer_success, indexer_message = verify_indexer_client()
    print(f"{'✅' if indexer_success else '❌'} {indexer_message}")
    
    # Exit with appropriate status code
    sys.exit(0 if algod_success and indexer_success else 1)

if __name__ == "__main__":
    main() 