import requests
import os


def main():
    # API endpoint URL
    url = "https://asa-list.tinyman.org/assets.json"

    # Download directory
    download_dir = "/Users/nikitagorokhov/metafarm-frontend/src/imgs/icons"

    # Make sure the download directory exists
    os.makedirs(download_dir, exist_ok=True)

    # Call the API to get the asset data
    response = requests.get(url)

    # Check if the API call was successful
    if response.status_code == 200:
        # Parse the JSON response
        asset_data = response.json()

        # Iterate over each asset entry
        for asset_id, asset_info in asset_data.items():
            # Get the logo PNG URL
            logo_url = asset_info['logo']['png']

            # Download the logo image
            logo_response = requests.get(logo_url)

            # Check if the logo download was successful
            if logo_response.status_code == 200:
                # Save the logo image to a file
                file_path = os.path.join(download_dir, f"{asset_id}.png")
                with open(file_path, "wb") as file:
                    file.write(logo_response.content)
                print(f"Downloaded logo for asset {asset_id}")
            else:
                print(f"Failed to download logo for asset {asset_id}")
    else:
        print("Failed to retrieve asset data from the API")


if __name__ == "__main__":
    main()
