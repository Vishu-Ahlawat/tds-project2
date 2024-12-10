# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas", "seaborn", "matplotlib", "openai", "httpx","chardet","requests","scikit-learn"]
# ///



import os
import sys
import pandas as pd
import chardet 
import json
import requests
import seaborn as sns
import matplotlib.pyplot as plt
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
import base64




def load_dataset(file_path):
    """
    Load a dataset with automatic encoding detection.
    
    :param file_path: Path to the dataset file
    :return: pandas DataFrame or None if an error occurs
    """
    try:
        # Detect encoding as it is not safe to assume unknown dataset is encoded using regular utf-8 or any other encoding.
        with open(file_path, 'rb') as f:
            result = chardet.detect(f.read())  # Detect encoding from the whole file as only leading part may be misleading
            detected_encoding = result['encoding']
        
        # Load dataset
        df = pd.read_csv(file_path, encoding=detected_encoding)
        #print(f"Dataset loaded: {file_path}, shape: {df.shape}")
        if df is None or df.empty:
            sys.exit("The dataset is empty or failed to load.")
        return df
    
    except Exception as e:
        print(f"Failed to load dataset: {e}")
        sys.exit(1)

def get_headers_as_json(df):
    """
    Function to extract column headers from a DataFrame and return them as a JSON object.json objects because it'll be easier to communicate with llm and less processing will be required.
    :param df: pandas DataFrame
    :return: JSON string containing column headers
    """
    # Get column headers as a list
    headers = df.columns.tolist()
    # Convert to JSON
    headers_json = json.dumps({"headers": headers})
    
    return headers_json

def profile_dataset(df):
    """
    Generate a basic profile of the dataset.
    :param df: pandas DataFrame
    :return: Summary as a dictionary
    """
    # Generate summary of the dataset that includes shape, null values, dtypes, numerical summary and 3 samples of data
    headers = get_headers_as_json(df)
    summary = {
        "shape": df.shape,
        "null_values": df.isnull().sum().to_dict(),
        "dtypes": df.dtypes.apply(str).to_dict(),
        "numerical_summary": df.describe().to_dict(),
        "headers": headers,
        "sample_data": df.head(3).to_dict()
    }
    return summary


def generate_scatterplot(df, profile, api_key, output_dir):
    # post to the llm endpoint and get the response
    response = requests.post(
        "https://aiproxy.sanand.workers.dev/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "gpt-4o-mini",  # can be any other
            "messages": [
                {
                    "role": "system",
                    "content": "Given the following dataset analysis, suggest two numeric columns from the dataset that would make an interesting scatterplot. Return only the column names, separated by a comma. No explanation needed. If there is not enough numeric columns, return empty string only."
                },
                {
                    "role": "user",
                    "content": str(profile)
                }
            ]
        }
    )

    # return empty in any undesired case to stop the function from running further and failing along with the try-except blocks
    # Get the fields for scatterplot from the response
    try:
        fields_for_scatterplot = response.json()['choices'][0]['message']["content"].split(',')
    except (KeyError, IndexError, TypeError):
        return 

    # Ensure exactly two columns are returned
    if len(fields_for_scatterplot) != 2:
        return

    # Strip any extra spaces from the column names
    fields_for_scatterplot = [field.strip() for field in fields_for_scatterplot]
    x_column, y_column = fields_for_scatterplot

    # Ensure columns exist in the DataFrame and are numeric
    if x_column not in df.columns or y_column not in df.columns:
        return
    if not pd.api.types.is_numeric_dtype(df[x_column]) or not pd.api.types.is_numeric_dtype(df[y_column]):
        return

    # Convert to numeric values, coercing errors to NaN (which can be dropped later)
    df[x_column] = pd.to_numeric(df[x_column], errors='coerce')
    df[y_column] = pd.to_numeric(df[y_column], errors='coerce')

    # Drop rows with NaN values in either of the selected columns
    df_cleaned = df.dropna(subset=[x_column, y_column])

    # Ensure there are enough data points to plot
    if df_cleaned.empty:
        return

    # Plot the scatter plot using seaborn
    plt.figure(figsize=(8, 6))
    sns.scatterplot(data=df_cleaned, x=x_column, y=y_column)

    # Set plot title and labels
    plt.title(f'Scatterplot between {x_column} and {y_column}')
    plt.xlabel(x_column)
    plt.ylabel(y_column)
    #plt.show()
    # Save the plot as PNG
    output_path = os.path.join(output_dir, f'{x_column}_{y_column}_scatterplot.png')
    plt.savefig(output_path)
    plt.close()

    




def generate_correlation_heatmap(df, output_dir):
    # Select only numeric columns
    numeric_columns = df.select_dtypes(include=['number'])
    
    # Check if there are at least 2 numeric columns which is requirement for correlation
    if len(numeric_columns.columns) < 2:
        return

    # Compute the correlation matrix
    correlation_matrix = numeric_columns.corr()

    # Create the heatmap
    plt.figure(figsize=(10, 8))
    sns.heatmap(correlation_matrix, annot=True, cmap='coolwarm', fmt=".2f", linewidths=0.5)
    plt.title('Correlation Heatmap')

    #plt.show()
    # Save the plot with a dynamic filename
    output_path = os.path.join(output_dir, 'correlation_heatmap.png')
    plt.savefig(output_path, bbox_inches='tight')
    
    # Close the plot to free up memory
    plt.close()




def generate_cluster_data(df, profile,api_key,output_dir):
    try:
        # post to the llm endpoint and get the response, using try block in case the server is down
        response = requests.post(
                "https://aiproxy.sanand.workers.dev/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "gpt-4o-mini", # can be anny other
                    "messages": [
                        {
                            "role": "system",
                            "content": '''Given the following dataset summary, which numeric columns are suitable for clustering? 
                                        Exclude any IDs or non-informative columns. Please provide a maximum of 5 columns. 
                                        Return only the column names, separated by a comma. No explanation needed
                                        also if the dataset is not suitable for clustering, return empty string only'''
                        },
                        {
                            "role": "user",
                            "content": str(profile)
                        }
                    ]
                }
            )
        
        response.raise_for_status()
        columns = response.json()['choices'][0]['message']['content'].split(',')
        columns = [col.strip() for col in columns if col.strip()]

        # Check if we have at least 2 columns for clustering
        if len(columns) < 2:
            print("Not enough suitable columns for clustering.")
            return ''

        # Ensure the selected columns are in the dataframe
        selected_columns = [col for col in columns if col in df.columns]

        if len(selected_columns) < 2:
            print("Selected columns are not present in the dataframe.")
            return ''

        # Handle missing values in the selected columns
        numeric_imputer = SimpleImputer(strategy='mean')
        df[selected_columns] = numeric_imputer.fit_transform(df[selected_columns])

        # Scale the numeric data
        scaler = StandardScaler()
        data_scaled = scaler.fit_transform(df[selected_columns])

        # Check if there are enough rows for clustering
        if len(df) < 3:
            print("Not enough data points for clustering.")
            return ''

        # Perform KMeans clustering
        n_clusters = 3
        kmeans = KMeans(n_clusters=n_clusters, random_state=42)
        df['Cluster'] = kmeans.fit_predict(data_scaled)

        # Generate scatterplot using the first two selected columns
        plt.figure(figsize=(8, 6))
        sns.scatterplot(x=df[selected_columns[0]], y=df[selected_columns[1]], hue=df['Cluster'], palette='viridis', s=100, alpha=0.7)
        plt.title('KMeans Clustering')
        plt.xlabel(selected_columns[0])
        plt.ylabel(selected_columns[1])
        plt.legend(title='Cluster')

        # Save the plot in the directory with a dynamic filename.
        output_path = os.path.join(output_dir, 'clustering_plot.png')
        plt.savefig(output_path)

        #plot just for checking
        #plt.show()
        plt.close()
        return 
    

    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
    except (KeyError, IndexError) as e:
        print(f"Unexpected response format: {e}")
        return None
    

# narrating the story and making README.md
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def get_image_analysis(api_key, image_path,header_of_data, sample_data):
    # Encode the image
    base64_image = encode_image(image_path)

    # Endpoint and headers
    endpoint = "https://aiproxy.sanand.workers.dev/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # Payload for the request
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"Create a detailed and engaging story based on this image. This is for a project and consider it as a report.I am also attaching headers and sample data for your clearance.\n\n headers:{header_of_data}\n\n sample data:{sample_data}"
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64_image}"
                        }
                    }
                ]
            }
        ]
    }

    try:
        response = requests.post(endpoint, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        story = result['choices'][0]['message']['content']
        return story
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
    except (KeyError, IndexError) as e:
        print(f"Unexpected response format: {e}")
        return None

def process_images_and_create_readme(dataset_file, api_key,headers_json,sample_data):
    # Get the output directory from the dataset file path
    output_dir = os.path.splitext(dataset_file)[0]

    # Ensure the directory exists
    if not os.path.exists(output_dir):
        print(f"Directory does not exist: {output_dir}")
        return

    # List all .png files in the directory
    images = [f for f in os.listdir(output_dir) if f.endswith('.png')]

    if not images:
        print("No PNG images found in the directory.")
        return

    # Initialize the README.md content
    readme_path = os.path.join(output_dir, "README.md")
    readme_content = "# Image Narratives\n\n"

    # Process each image
    for image in images:
        image_path = os.path.join(output_dir, image)
        print(f"Processing {image_path}...")

        # Get the story from the LLM
        story = get_image_analysis(api_key, image_path,headers_json,sample_data)

        if story:
            # Add the image and story to the README content
            readme_content += f"## {os.path.splitext(image)[0]}\n\n"
            readme_content += f"![{image}](./{image})\n\n"
            readme_content += f"{story}\n\n"
        else:
            print(f"Failed to generate a story for {image}.")

    # Write the README.md file
    with open(readme_path, "w", encoding="utf-8") as readme_file:
        readme_file.write(readme_content)

    print(f"README.md created at {readme_path}")




if __name__ == "__main__":
    try:
        #may be present or not, better to check
        api_key = os.environ["AIPROXY_TOKEN"]
    except KeyError:
        raise ValueError("AIPROXY_TOKEN environment variable not set.")
    def check_filepath():
        # 
        if len(sys.argv) < 2:
            print("Usage: uv run autolysis.py <dataset.csv>")
            sys.exit(1)

    dataset_file = sys.argv[1]

    check_filepath()
    df = load_dataset(dataset_file)

    headers_json = get_headers_as_json(df)
    sample_data = df.sample(n=5).to_string(index=False)


    # Perform dataset profiling for sending to llm
    profile = profile_dataset(df)
    #print(json.dumps(profile, indent=4))  #sanity check

    output_dir = os.path.splitext(dataset_file)[0]  # Remove file extension
    os.makedirs(output_dir, exist_ok=True)

    #run functions and generate visulizations
    generate_scatterplot(df, profile,api_key,output_dir)
    generate_correlation_heatmap(df,output_dir)
    generate_cluster_data(df, profile,api_key,output_dir)

    # narrate story in README.md
    process_images_and_create_readme(dataset_file, api_key,headers_json,sample_data)