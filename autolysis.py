# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas", "seaborn", "matplotlib", "openai", "httpx","chardet","requests","scikit-learn","numpy"]
# ///



import os
import sys
import pandas as pd
import numpy as np
import chardet 
import json
import requests
import seaborn as sns
import matplotlib.pyplot as plt
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.metrics import silhouette_score
import base64


# NOTES TO FOLLOW, NOT STRICTLY NECESSARY, MORE OF LIKE A ROADMAP
# ask llm to return empty string in case of the data is not suitable for any type of analysis 
# DRY : don't repeat yourself, except when using llm, which is a special case because changing structure may cause problems
# use vision models extensively for image analysis or story narration, because that's the main part
# i'll return empty string in any undesired case, because I am not sure whether logging is allowed while evaluation in someone else's environment 
# don't assume anything that is unknown; i.e. Dataset
# try to cover most of corner cases, like empty dataset, dataset with only one column, etc.
# use try-except block
# manage code quality and maintainability
# manage QRMS : quality, readability, maintainability, scaleability
# try to be in llm token limit.



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


def generate_scatterplot(df, output_dir):
    # Ensure there are numeric columns in the dataset
    numeric_columns = df.select_dtypes(include='number').columns.tolist()
   # print(f"Numeric columns: {numeric_columns}")
    
    if len(numeric_columns) < 2:
        print("Not enough numeric columns for a scatterplot.")
        return  # Not enough numeric columns for a scatterplot

    # Calculate the correlation matrix
    correlation_matrix = df[numeric_columns].corr()
    #rint(f"Correlation matrix: \n{correlation_matrix}")

    # Create a boolean mask for the upper triangle (excluding diagonal)
    upper_triangle_mask = np.triu(np.ones(correlation_matrix.shape), k=1).astype(bool)

    # Apply the mask to the correlation matrix
    upper_triangle = correlation_matrix.where(upper_triangle_mask)
    #print(f"Upper triangle of correlation matrix: \n{upper_triangle}")
    
    # Find the index of the maximum correlation
    try:
        max_corr_pair = upper_triangle.stack().idxmax()
        max_corr_value = upper_triangle.stack().max()
    except ValueError:
        print("No correlation pairs found.")
        return
    
    #print(f"Max correlation pair: {max_corr_pair} with value {max_corr_value}")

    # Extract the two columns for the scatterplot
    x_column, y_column = max_corr_pair

    # Ensure there are enough data points to plot
    if df.empty or pd.isna(max_corr_value):
        print("No valid data points for plotting.")
        return  # Return if no valid data points or correlations

    # Convert to numeric values, coercing errors to NaN (which can be dropped later)
    df[x_column] = pd.to_numeric(df[x_column], errors='coerce')
    df[y_column] = pd.to_numeric(df[y_column], errors='coerce')

    # Drop rows with NaN values in either of the selected columns
    df_cleaned = df.dropna(subset=[x_column, y_column])

    # Ensure there are enough data points to plot
    if df_cleaned.empty:
        print("No data points left after cleaning.")
        return

    # Plot the scatter plot using seaborn
    plt.figure(figsize=(8, 6))
    sns.scatterplot(data=df_cleaned, x=x_column, y=y_column)

    # Set plot title and labels
    plt.title(f'Scatterplot between {x_column} and {y_column}')
    plt.xlabel(x_column)
    plt.ylabel(y_column)
    x_column_safe = x_column.replace(" ", "_")
    y_column_safe = y_column.replace(" ", "_")
    # Save the plot as PNG (uncomment this if you want to save the plot)
    output_path = os.path.join(output_dir, f'{x_column_safe}_{y_column_safe}_scatterplot.png')
    print(f"Saving plot to {output_path}")
    plt.savefig(output_path, dpi=60, bbox_inches='tight')
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
    plt.savefig(output_path, dpi=60, bbox_inches='tight')
    
    # Close the plot to free up memory
    plt.close()




def find_optimal_k(data, max_k=5):
    """
    Determine the optimal number of clusters using the Elbow Method and Silhouette Score.
    """
    inertias = []
    silhouette_scores = []

    # Test for k values from 2 to max_k
    for k in range(2, max_k + 1):
        kmeans = KMeans(n_clusters=k, random_state=42, n_init='auto')
        labels = kmeans.fit_predict(data)
        inertias.append(kmeans.inertia_)
        silhouette_scores.append(silhouette_score(data, labels))

    

    # Choose k based on the highest silhouette score
    optimal_k = range(2, max_k + 1)[np.argmax(silhouette_scores)]
    return optimal_k


def generate_cluster_data(df, output_dir, max_columns=10, max_k=5, sample_size=500):
    """
    Perform clustering on a dataset and save a scatterplot of the clusters.

    Parameters:
    - df: DataFrame containing the data.
    - output_dir: Directory to save the clustering plot.
    - max_columns: Maximum number of columns to consider for clustering.
    - max_k: Maximum number of clusters to test for.
    - sample_size: Number of rows to sample if the dataset is too large.
    """
    # Step 1: Select numeric columns and exclude potential ID-like columns
    numeric_columns = df.select_dtypes(include='number').columns.tolist()
    excluded_keywords = ['id', 'ID']
    suitable_columns = [col for col in numeric_columns if not any(keyword in col.lower() for keyword in excluded_keywords)]

    if len(suitable_columns) < 2:
        print("Not enough suitable numeric columns for clustering.")
        return ''

    # Step 2: Select up to max_columns with the highest variance
    variances = df[suitable_columns].var()
    high_variance_columns = variances.nlargest(max_columns).index.tolist()

    if len(high_variance_columns) < 2:
        print("Not enough high-variance columns for clustering.")
        return ''

    # Step 3: Sample the data if it’s too large
    if len(df) > sample_size:
        df = df.sample(n=sample_size, random_state=42)

    # Step 4: Handle missing values
    numeric_imputer = SimpleImputer(strategy='mean')
    df[high_variance_columns] = numeric_imputer.fit_transform(df[high_variance_columns])

    # Step 5: Scale the numeric data
    scaler = StandardScaler()
    data_scaled = scaler.fit_transform(df[high_variance_columns])

    # Step 6: Determine the optimal number of clusters
    optimal_k = find_optimal_k(data_scaled, max_k)
    print(f"Optimal number of clusters: {optimal_k}")

    # Step 7: Perform KMeans clustering with the optimal k
    kmeans = KMeans(n_clusters=optimal_k, random_state=42)
    df['Cluster'] = kmeans.fit_predict(data_scaled)

    # Step 8: Generate scatterplot using the first two selected columns
    plt.figure(figsize=(8, 6))
    sns.scatterplot(
        x=df[high_variance_columns[0]],
        y=df[high_variance_columns[1]],
        hue=df['Cluster'],
        palette='viridis',
        s=100,
        alpha=0.7
    )

    plt.title(f'KMeans Clustering with k={optimal_k}')
    plt.xlabel(high_variance_columns[0])
    plt.ylabel(high_variance_columns[1])
    plt.legend(title='Cluster')

    # Save the plot
    output_path = os.path.join(output_dir, 'clustering_plot.png')
    plt.savefig(output_path, dpi=60, bbox_inches='tight')
    print(f"Clustering plot saved to {output_path}")
    #plt.show()
    plt.close()
    return ''
    

# narrating the story and making README.md
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def get_batched_image_analysis(api_key, image_paths, headers_json):
    # Endpoint and headers
    endpoint = "https://aiproxy.sanand.workers.dev/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # Prepare the payload with multiple images
    messages_content = [
        {
            "type": "text",
            "text": (
                "For each image, generate a concise and insightful story based on its content. "
                "Label each story with the corresponding image identifier (e.g., Image 1, Image 2, etc.)."
                "Make sure to always label image with 3 # (eg. ### Image 1, ### Image 2). "
                "make the story atleat 250 words long for each image. "
                "Focus on trends, patterns, and data structure. Headers for context are provided, don't use these in your story: "
                f"{headers_json}."
            )
        }
    ]

    # Add each image to the payload
    for idx, image_path in enumerate(image_paths, start=1):
        base64_image = encode_image(image_path)
        messages_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{base64_image}"}
        })

    # Complete payload for the request
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": messages_content}]
    }

    try:
        response = requests.post(endpoint, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        #print(result['choices'][0]['message']['content'])
        return result['choices'][0]['message']['content']
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None
    except (KeyError, IndexError) as e:
        print(f"Unexpected response format: {e}")
        return None

def process_images_and_create_readme(df, dataset_file, api_key, headers_json):
    output_dir = os.path.splitext(dataset_file)[0]

    if not os.path.exists(output_dir):
        print(f"Directory does not exist: {output_dir}")
        return

    images = [os.path.join(output_dir, f) for f in os.listdir(output_dir) if f.endswith('.png')]

    if not images:
        print("No PNG images found in the directory.")
        return

    # Get batched stories for all images
    batched_stories = get_batched_image_analysis(api_key, images, headers_json)
    if not batched_stories:
        print("Failed to generate stories for the images.")
        return

    # Split the batched stories based on the labels "Image 1", "Image 2", etc.
    # Split the batched stories based on the headers "### Image 1", "### Image 2", etc.
    stories = {}
    current_label = None
    current_story = []

    # Split batched stories based on the "### Image X" header
    for line in batched_stories.splitlines():

        if line.startswith("### Image"):
            if current_label and current_story:
                # Save the current story for the previous image
                stories[current_label] = "\n".join(current_story).strip()

            # Extract image number (e.g., 1, 2, 3)
            current_label = line.split()[2]  # Get the number part of "### Image X"
            current_story = []  # Reset current story
        else:
            current_story.append(line)

    # Save the last story
    if current_label and current_story:
        stories[current_label] = "\n".join(current_story).strip()

    # Debugging: print the stories dictionary
    #print("Stories Dictionary:", stories)


    # Initialize the README.md content
    readme_path = os.path.join(output_dir, "README.md")
    readme_content = "# Image Narratives\n\n"

    # Process each image and its corresponding story
    for idx, image_path in enumerate(images, start=1):
        image_name = os.path.basename(image_path)
        story = stories.get(str(idx), "No story available for this image.")

        readme_content += f"## {os.path.splitext(image_name)[0]}\n\n"
        readme_content += f"![{image_name}](./{image_name})\n\n"
        readme_content += f"{story}\n\n"

    # Write the README.md file
    with open(readme_path, "w", encoding="utf-8") as readme_file:
        readme_file.write(readme_content)
        readme_file.write('\n\n## Some more key insights from the data:\n\n')
        
        # Top column analysis
        top_column = df.describe().loc['mean'].idxmax()
        narrative = f"- The column '{top_column}' has the highest average value among numerical features.\n\n"
        readme_file.write(narrative)
        
        # Correlation analysis
        corr_matrix = df.select_dtypes(include=[float, int]).corr()
        highest_corr = corr_matrix.abs().unstack().sort_values(ascending=False).drop_duplicates()

        # Skip self-correlation (where features are compared to themselves)
        highest_corr = highest_corr[highest_corr < 1]

        # Get the highest correlation pair and the correlation value
        feature_pair, correlation = highest_corr.idxmax(), highest_corr.max()

        # Now you can use the feature pair and the correlation
        narrative1 = f"- The highest correlation is between '{feature_pair[0]}' and '{feature_pair[1]}' with a value of {correlation:.2f}.\n\n"

        if correlation > 0.7:
            narrative2 = f"- This indicates a strong positive correlation between the features '{feature_pair[0]}' and '{feature_pair[1]}'. Growth of one feature is often associated with the growth of the other feature.\n\n"
        elif correlation < -0.7:
            narrative2 = f"- This indicates a strong negative correlation between the features '{feature_pair[0]}' and '{feature_pair[1]}'. Growth of one feature is often associated with the decline of the other feature.\n\n"
        else:
            narrative2 = f"- This indicates a weak correlation between the features '{feature_pair[0]}' and '{feature_pair[1]}'. They are correlated but not strongly.\n\n"
        readme_file.write(narrative1)
        readme_file.write(narrative2)
        number_of_Rows=df.shape[0]
        number_of_Columns=df.shape[1]
        if number_of_Rows > 1000:
            narrative3 = "- The dataset has more than 1000 rows. It is good for analysis but it may not be suitable for training models, so choose wisely.\n\n"
        else:
            narrative3 = "- The dataset have less than 1000 rows. So making any huge analysis may not be a good idea.\n\n"
        readme_file.write(narrative3)
        if number_of_Columns > 20:
            narrative4 = "- The dataset has more than 20 columns. It is good for analysis but make sure to use feature selection or dimensionality reduction techniques if necessary.\n\n\n"
        else:
            narrative4 = "- The dataset have less than 20 columns. So it may be ideal to use all the columns if number of rows is also less.\n\n"
        readme_file.write(narrative4)

    print(f"README.md created at {readme_path}")






if __name__ == "__main__":
    try:
        # may be present or not, better to check
        api_key = os.environ["AIPROXY_TOKEN"]
    except KeyError:
        raise ValueError("AIPROXY_TOKEN environment variable not set.")
    def check_filepath():
        # if no filepath is provided
        if len(sys.argv) < 2:
            print("Usage: uv run autolysis.py <dataset.csv>")
            sys.exit(1)
    # if provided, we can try to get the file. If it is valid or not, it'll be checked by the function load_dataset defined earlier
    dataset_file = sys.argv[1]

    check_filepath()
    df = load_dataset(dataset_file)

    headers_json = get_headers_as_json(df)
    # to make sure data is not empty, it is also checked in load_dataset also
    sample_data = df.sample(n=min(5, len(df))).to_string(index=False)


    # Perform dataset profiling for sending to llm
    profile = profile_dataset(df)
    #print(json.dumps(profile, indent=4))  #sanity check

    output_dir = os.path.splitext(dataset_file)[0]  # Remove file extension
    os.makedirs(output_dir, exist_ok=True)

    #run functions and generate visulizations
    generate_scatterplot(df,output_dir)
    generate_correlation_heatmap(df,output_dir)
    generate_cluster_data(df, output_dir)

    # narrate story in README.md
    process_images_and_create_readme(df,dataset_file, api_key,headers_json)
