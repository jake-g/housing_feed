import logging
import os
import re
from typing import Any, Dict, List, Optional

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

# Constants
MIN_PRICE = 400000
MIN_SQFT = 100

# Plotting Constraints
MIN_PLOT_PRICE = 500000
MAX_PLOT_PRICE = 1500000

# Mapping from Zip Code to Neighborhood Name
ZIP_NEIGHBORHOOD_MAP = {
    98101: 'Downtown',
    98102: 'Eastlake',
    98103: 'Green Lake',
    98104: 'Pioneer Sq',
    98105: 'U-District',
    98106: 'Delridge',
    98107: 'Ballard',
    98108: 'Georgetown',
    98109: 'Queen Anne',
    98112: 'Madison Park',
    98115: 'Wedgwood/View Ridge',
    98116: 'Alki/Admiral',
    98117: 'Ballard (N)',
    98118: 'Columbia City',
    98119: 'Queen Anne',
    98121: 'Belltown',
    98122: 'Central District',
    98125: 'Lake City',
    98126: 'High Point',
    98133: 'Bitter Lake',
    98136: 'Fauntleroy',
    98144: 'Mt Baker',
    98199: 'Magnolia',
}


def get_neighborhood_label(zip_code: int) -> str:
  """Returns a readable label for a zip code (e.g. 'Ballard (98107)')."""
  name = ZIP_NEIGHBORHOOD_MAP.get(zip_code, 'Unknown')
  return f"{name} ({zip_code})"



def setup_logging(script_name: str, log_level: int = logging.INFO) -> None:
  """Configures logging to both file and console.

  Args:
      script_name: Name of the script/log file (e.g., 'fetch_emails').
      log_level: Logging level (default: logging.INFO).
  """
  os.makedirs('logs', exist_ok=True)
  log_file = f"logs/{script_name}.log"
  log_format = '%(asctime)s - %(levelname)s - %(message)s'

  root_logger = logging.getLogger()
  if root_logger.hasHandlers():
    root_logger.handlers.clear()

  # Create handlers
  file_handler = logging.FileHandler(log_file, mode='w')
  file_handler.setLevel(log_level)
  file_handler.setFormatter(logging.Formatter(log_format))

  stream_handler = logging.StreamHandler()
  stream_handler.setLevel(log_level)
  stream_handler.setFormatter(logging.Formatter(log_format))

  logging.basicConfig(level=log_level,
                      handlers=[file_handler, stream_handler],
                      datefmt='%Y-%m-%d %H:%M:%S')

  # Suppress overly verbose third-party logs
  logging.getLogger("urllib3").setLevel(logging.WARNING)


def configure_plotting_style():
  """Sets professional plotting style."""
  try:
    # Use seaborn style if available, otherwise fallback to matplotlib default
    sns.set_theme(style="whitegrid", context="paper", font_scale=1.2)
    plt.rcParams['figure.figsize'] = (12, 8)
    plt.rcParams['axes.titlesize'] = 16
    plt.rcParams['axes.labelsize'] = 14
    plt.rcParams['xtick.labelsize'] = 12
    plt.rcParams['ytick.labelsize'] = 12
    plt.rcParams['legend.fontsize'] = 12

    # Silence matplotlib info logs
    logging.getLogger('matplotlib.category').setLevel(logging.WARNING)
    logging.getLogger('matplotlib.font_manager').setLevel(logging.WARNING)
    logging.getLogger('matplotlib.ticker').setLevel(logging.WARNING)
  except ImportError:
    plt.style.use('ggplot')


def format_currency_axis(x, pos):
  """Formatter for currency axis (e.g., $500k, $1.2M)."""
  if x >= 1_000_000:
    return f'${x*1e-6:,.1f}M'
  return f'${x*1e-3:,.0f}k'


def plot_price_distribution(df: pd.DataFrame,
                            bins: int = 20,
                            color: str = 'teal') -> Optional[str]:
  """Generates and saves the price distribution histogram.

  Args:
      df: DataFrame containing price data.
      bins: Number of histogram bins.
      color: Color of the histogram bars.

  Returns:
      Filename of the saved plot, or None if skipped.
  """
  if 'Price' not in df.columns:
    return None

  plt.figure(figsize=(10, 6))
  pdf = df.dropna(subset=['Price'])

  if pdf.empty:
    return None

  # Clip top 1% for better histogram, but also respect global plot bounds
  # q_high = pdf['Price'].quantile(0.99)
  # pdf = pdf[(pdf['Price'] < q_high) & (pdf['Price'] > MIN_PRICE)]
  # Use standard bounds
  pdf = pdf[(pdf['Price'] >= MIN_PLOT_PRICE) & (pdf['Price'] <= MAX_PLOT_PRICE)]

  if pdf.empty:
    return None

  ax = sns.histplot(pdf['Price'],
                    bins=30,
                    kde=False,
                    color='skyblue',
                    edgecolor='white')

  # Add mean and median lines for context
  mean_price = pdf['Price'].mean()
  median_price = pdf['Price'].median()

  plt.axvline(mean_price,
              color='red',
              linestyle='--',
              linewidth=1.5,
              label=f'Mean: ${mean_price/1000:.0f}k')
  plt.axvline(median_price,
              color='green',
              linestyle='-',
              linewidth=1.5,
              label=f'Median: ${median_price/1000:.0f}k')

  plt.legend()

  plt.gca().xaxis.set_major_formatter(plt.FuncFormatter(format_currency_axis))
  plt.title('Price Distribution')
  plt.xlabel('Price')
  plt.ylabel('Count')

  filename = 'plots/price_dist.png'
  plt.tight_layout()
  plt.savefig(filename, dpi=300)
  plt.close()
  return filename


def plot_monthly_volume(df: pd.DataFrame) -> Optional[str]:
  """Generates and saves a stacked bar chart of monthly volume by property type.

  Args:
      df: DataFrame containing Date and Property_Type columns.

  Returns:
      Filename of the saved plot, or None if skipped.
  """
  if 'Date' not in df.columns or 'Property_Type' not in df.columns:
    return None

  # Ensure Date is datetime
  df['Date'] = pd.to_datetime(df['Date'], utc=True)

  # Filter out future dates or bad data
  # df = df[df['Date'] <= pd.Timestamp.now(tz='UTC')]

  if 'Price' in df.columns:
    # Filter by price for this plot too to be consistent
    df = df[(df['Price'] >= MIN_PLOT_PRICE) & (df['Price'] <= MAX_PLOT_PRICE)]

  # Resample by Month and count by property type
  monthly_volume = df.groupby(
      [pd.Grouper(key='Date', freq='ME'),
       'Property_Type']).size().unstack(fill_value=0)

  if monthly_volume.empty:
    return None

  # Plot
  plt.figure(figsize=(12, 6))
  # Use a colormap that handles many categories well
  monthly_volume.plot(kind='bar',
                      stacked=True,
                      figsize=(12, 6),
                      colormap='tab20')

  plt.title('Monthly Volume by Property Type')
  plt.xlabel('Month')
  plt.ylabel('Number of Listings')
  plt.legend(title='Property Type', bbox_to_anchor=(1.05, 1), loc='upper left')

  # Format x-axis labels to be readable dates (YYYY-MM)
  ax = plt.gca()
  labels = [item.get_text()[:7] for item in ax.get_xticklabels()]
  ax.set_xticklabels(labels, rotation=45, ha='right')

  filename = 'plots/monthly_volume.png'
  plt.tight_layout()
  plt.savefig(filename, dpi=300)
  plt.close()
  return filename


def plot_categorical_pies(df: pd.DataFrame) -> Optional[str]:
  """Generates a row of pie charts for Property Type, Beds, and Baths.

  Args:
      df: DataFrame containing categorical columns.

  Returns:
      Filename of the saved plot, or None.
  """
  cols = ['Property_Type', 'Beds', 'Baths']
  valid_cols = [c for c in cols if c in df.columns]

  if not valid_cols:
    return None

  # squeeze=False ensures axes is always an array
  fig, axes = plt.subplots(1,
                           len(valid_cols),
                           figsize=(6 * len(valid_cols), 6),
                           squeeze=False)
  axes = axes.flatten()

  has_data = False
  for ax, col in zip(axes, valid_cols):
    # Clean data for plotting
    data = df[col].dropna().astype(str)
    # Simplify: Top 5 + Others
    counts = data.value_counts()
    if counts.empty:
      ax.axis('off')
      continue

    has_data = True

    if len(counts) > 6:
      top_5 = counts.head(5)
      others = pd.Series({'Other': counts.iloc[5:].sum()})
      counts = pd.concat([top_5, others])

    # Traditional Pie (no wedgeprops width)
    # Filter for labels > 2% for clarity
    labels = [
        l if (c / counts.sum()) > 0.02 else ''
        for l, c in zip(counts.index, counts)
    ]

    wedges, texts, autotexts = ax.pie(counts,
                                      labels=labels,
                                      autopct=lambda p: f'{p:.1f}%'
                                      if p > 2 else '',
                                      startangle=90,
                                      colors=sns.color_palette('pastel'),
                                      pctdistance=0.85)

    # Draw circle for donut chart style (optional, looks modern)
    # centre_circle = plt.Circle((0,0),0.70,fc='white')
    # ax.add_artist(centre_circle)

    ax.set_title(f'{col} Distribution', fontweight='bold', pad=20)
    # Equal aspect ratio ensures that pie is drawn as a circle
    ax.axis('equal')

  if not has_data:
    plt.close()
    return None

  filename = 'plots/categorical_pies.png'
  plt.tight_layout()
  plt.savefig(filename, dpi=300)
  plt.close()
  return filename


def generate_plots(df: pd.DataFrame) -> List[str]:
  """Generates enhanced visualizations and returns a list of saved image paths."""
  if df.empty:
    return []

  os.makedirs('plots', exist_ok=True)
  plot_files = []
  configure_plotting_style()

  # ensure date is datetime
  if 'Date' in df.columns:
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce', utc=True)

  # Data Cleaning & Filtering for Plots
  if 'Price' in df.columns:
    df['Price'] = pd.to_numeric(df['Price'], errors='coerce')

  for col in ['Sqft', 'Beds', 'Baths']:
    if col in df.columns:
      df[col] = pd.to_numeric(df[col], errors='coerce')

  # Keep a clean copy for plotting
  plot_df = df.copy()

  # aggressive dropna for numerical fields we plot
  plot_df = plot_df.dropna(subset=['Price'])

  if 'Price' in plot_df.columns:
    plot_df['Price'] = pd.to_numeric(plot_df['Price'], errors='coerce')
    # Aggressive filtering for plotting window
    plot_df = plot_df[(plot_df['Price'] >= MIN_PLOT_PRICE) &
                      (plot_df['Price'] <= MAX_PLOT_PRICE)]

  if 'Sqft' in plot_df.columns:
    plot_df['Sqft'] = pd.to_numeric(plot_df['Sqft'], errors='coerce')
    plot_df = plot_df[plot_df['Sqft'] > MIN_SQFT]

  # Fill missing Property_Type
  if 'Property_Type' in plot_df.columns:
    plot_df['Property_Type'] = plot_df['Property_Type'].fillna(
        'Unknown').replace('', 'Unknown')

  # Monthly Volume
  vol_plot = plot_monthly_volume(df)
  if vol_plot:
    plot_files.append(vol_plot)

  # Categorical Pies
  pie_plot = plot_categorical_pies(df)
  if pie_plot:
    plot_files.append(pie_plot)

  if 'Zip' in plot_df.columns and 'Price' in plot_df.columns:
    plt.figure(figsize=(12, 8))

    # Filter top 15 Zips by count
    top_zips = plot_df['Zip'].value_counts().head(15).index
    pdf = plot_df[plot_df['Zip'].isin(top_zips)].copy()
    pdf['Zip'] = pdf['Zip'].astype(int)

    # Order by median price
    order = pdf.groupby('Zip')['Price'].median().sort_values().index

    ax = sns.boxplot(x='Price',
                     y='Zip',
                     data=pdf,
                     order=order,
                     hue='Zip',
                     legend=False,
                     palette='rainbow',
                     orient='h')

    # Update y-axis labels to include neighborhood names
    # set_ticks first to avoid UserWarning
    current_labels = [int(label.get_text()) for label in ax.get_yticklabels()]
    new_labels = [get_neighborhood_label(z) for z in current_labels]

    ax.set_yticks(range(len(new_labels)))
    ax.set_yticklabels(new_labels)

    ax.xaxis.set_major_formatter(plt.FuncFormatter(format_currency_axis))
    plt.title('Price Distribution by Top 15 Zip Codes', fontweight='bold')
    plt.xlabel('Price (Millions)')
    plt.ylabel('Zip Code')
    plt.xlim(MIN_PLOT_PRICE, MAX_PLOT_PRICE)
    plt.grid(axis='x', linestyle='--', alpha=0.7)

    filename = 'plots/price_distribution_by_zip.png'
    plt.tight_layout()
    plt.savefig(filename, dpi=300)
    plt.close()
    plot_files.append(filename)

  # Price per Sqft by Zip Code
  if 'Zip' in plot_df.columns and 'Price' in plot_df.columns and 'Sqft' in plot_df.columns:
    plt.figure(figsize=(12, 8))

    # Filter top 15 Zips by count
    top_zips = plot_df['Zip'].value_counts().head(15).index
    pdf = plot_df[plot_df['Zip'].isin(top_zips)].copy()
    pdf['Zip'] = pdf['Zip'].astype(int)

    # Calculate PPS
    pdf['PPS'] = pdf['Price'] / pdf['Sqft']
    # Filter reasonable PPS
    pdf = pdf[(pdf['PPS'] > 100) & (pdf['PPS'] < 2000)]

    # Order by median PPS
    order = pdf.groupby('Zip')['PPS'].median().sort_values().index

    ax = sns.boxplot(x='PPS',
                     y='Zip',
                     data=pdf,
                     order=order,
                     hue='Zip',
                     legend=False,
                     palette='coolwarm',
                     orient='h')

    # Update y-axis labels
    current_labels = [int(label.get_text()) for label in ax.get_yticklabels()]
    new_labels = [get_neighborhood_label(z) for z in current_labels]

    ax.set_yticks(range(len(new_labels)))
    ax.set_yticklabels(new_labels)

    # Format x-axis as currency
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))

    plt.title('Price per Sq. Ft. by Top 15 Zip Codes', fontweight='bold')
    plt.xlabel('Price per Sq. Ft.')
    plt.ylabel('Zip Code')
    plt.grid(axis='x', linestyle='--', alpha=0.7)

    filename = 'plots/pps_by_zip.png'
    plt.tight_layout()
    plt.savefig(filename, dpi=300)
    plt.close()
    plot_files.append(filename)

  # Time Series: Price Trends per Zip Code (with Shading)
  if 'Date' in df.columns and 'Price' in df.columns and 'Zip' in df.columns:
    plt.figure(figsize=(14, 8))

    # Filter for valid dates and top 5 Zips mostly
    valid_df = df.dropna(subset=['Date', 'Price', 'Zip']).copy()
    valid_df['Zip'] = valid_df['Zip'].astype(int)
    top_zips_5 = valid_df['Zip'].value_counts().head(5).index

    # Resample to monthly to smooth data
    # We need to set Date as index
    valid_df.set_index('Date', inplace=True)

    colors = sns.color_palette('husl', len(top_zips_5))

    for i, zipcode in enumerate(top_zips_5):
      zip_data = valid_df[valid_df['Zip'] == zipcode]
      # Filter 0 prices within the zip data too
      zip_data = zip_data[(zip_data['Price'] >= MIN_PLOT_PRICE) &
                          (zip_data['Price'] <= MAX_PLOT_PRICE)]
      if zip_data.empty:
        continue

      # Resample to monthly median and IQR
      monthly_stats = zip_data['Price'].resample('ME').agg(
          ['median', lambda x: x.quantile(0.25), lambda x: x.quantile(0.75)])
      monthly_stats.columns = ['median', 'q25', 'q75']

      # Drop NaN
      monthly_stats = monthly_stats.dropna()

      if monthly_stats.empty:
        continue

      plt.plot(monthly_stats.index,
               monthly_stats['median'],
               marker='o',
               label=get_neighborhood_label(zipcode),
               color=colors[i],
               linewidth=2)
      plt.fill_between(monthly_stats.index,
                       monthly_stats['q25'],
                       monthly_stats['q75'],
                       color=colors[i],
                       alpha=0.15)

    plt.gca().yaxis.set_major_formatter(plt.FuncFormatter(format_currency_axis))
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    plt.title('Price Trends Over Time (Top 5 Zip Codes) - Median & IQR')
    plt.ylabel('Sold Price')
    plt.xlabel('Date')
    plt.legend(title='Neighborhood', loc='upper left')
    plt.grid(True, linestyle='--', alpha=0.5)

    filename = 'plots/price_trends_time_series.png'
    plt.tight_layout()
    plt.savefig(filename, dpi=300)
    plt.close()
    plt.close()
    plot_files.append(filename)

  # Price vs Sqft Scatter Plot
  if 'Price' in df.columns and 'Sqft' in df.columns and 'Property_Type' in df.columns:
    plt.figure(figsize=(10, 8))

    # Filter out extreme outliers for better visualization
    pdf = df.dropna(subset=['Price', 'Sqft', 'Property_Type'])
    # Optional: clip upper 1%
    q_price = pdf['Price'].quantile(0.99)
    q_sqft_hi = pdf['Sqft'].quantile(0.99)
    q_sqft_lo = pdf['Sqft'].quantile(0.01)

    pdf = pdf[(pdf['Price'] >= MIN_PLOT_PRICE) &
              (pdf['Price'] <= MAX_PLOT_PRICE) & (pdf['Sqft'] <= q_sqft_hi) &
              (pdf['Sqft'] >= q_sqft_lo)]

    # Sort so 'Unknown' is first (plotted first -> behind others)
    # Create a sort key: 0 for Unknown, 1 for others
    pdf['sort_key'] = pdf['Property_Type'].apply(lambda x: 0
                                                 if x == 'Unknown' else 1)
    pdf = pdf.sort_values(by=['sort_key', 'Property_Type'])

    # Define consistent colors for property types
    prop_types = sorted(pdf['Property_Type'].unique())
    palette = sns.color_palette("bright", len(prop_types))
    type_colors = dict(zip(prop_types, palette))

    # Ensure Unknown is grey if we want, or just let it be.
    # User just asked for it to be behind.
    if 'Unknown' in type_colors:
      type_colors['Unknown'] = (
          0.8, 0.8, 0.8
      )  # Light grey for unknown matches user intent of "background"

    sns.scatterplot(
        data=pdf,
        x='Sqft',
        y='Price',
        hue='Property_Type',
        alpha=0.6,  # Slightly more opaque since we have layering
        palette=type_colors,
        s=15)

    plt.gca().yaxis.set_major_formatter(plt.FuncFormatter(format_currency_axis))
    plt.gca().xaxis.set_major_formatter(
        plt.FuncFormatter(lambda x, p: f'{x:,.0f}'))

    plt.title('Price vs Square Footage')
    plt.xlabel('Square Footage')
    plt.ylabel('Price')
    plt.legend(title='Property Type')

    filename = 'plots/price_vs_sqft.png'
    plt.tight_layout()
    plt.savefig(filename, dpi=300)
    plt.close()
    plot_files.append(filename)

    # Price Distribution Histogram
    dist_plot = plot_price_distribution(df)
    if dist_plot:
      plot_files.append(dist_plot)

  # Zip Code Feature Analysis (Avg Sqft, Beds, Baths)
  if 'Zip' in plot_df.columns and all(
      c in plot_df.columns for c in ['Sqft', 'Beds', 'Baths']):
    plt.figure(figsize=(12, 10))

    # Filter top 10 Zips
    top_zips_10 = plot_df['Zip'].value_counts().head(10).index
    zdf = plot_df[plot_df['Zip'].isin(top_zips_10)].copy()
    zdf['Zip'] = zdf['Zip'].astype(int)

    # Normalize fields for comparison or just plot raw with subplots?
    # Subplots are better for different units
    fig, axes = plt.subplots(3, 1, figsize=(10, 15), sharex=True)

    sns.barplot(data=zdf,
                x='Zip',
                y='Sqft',
                hue='Zip',
                legend=False,
                ax=axes[0],
                estimator='mean',
                errorbar=None,
                palette='Blues_d')
    axes[0].set_title('Average Square Footage by Neighborhood')
    axes[0].set_ylabel('Sq Ft')
    # Hide x-axis labels for top subplots
    axes[0].tick_params(labelbottom=False)

    sns.barplot(data=zdf,
                x='Zip',
                y='Beds',
                hue='Zip',
                legend=False,
                ax=axes[1],
                estimator='mean',
                errorbar=None,
                palette='Greens_d')
    axes[1].set_title('Average Beds by Neighborhood')
    axes[1].set_ylabel('Beds')
    axes[1].tick_params(labelbottom=False)

    sns.barplot(data=zdf,
                x='Zip',
                y='Baths',
                hue='Zip',
                legend=False,
                ax=axes[2],
                estimator='mean',
                errorbar=None,
                palette='Reds_d')
    axes[2].set_title('Average Baths by Neighborhood')
    axes[2].set_ylabel('Baths')
    axes[2].set_xlabel('Neighborhood')

    # Set x-tick labels (rotated for readability)
    # But usually it's sorted by x if numeric? No, it's categorical.
    # We didn't specify order, so it might be random. Let's fix order to match value counts or something?
    # Actually, zdf is top 10 zips. Let's assume consistent order.
    # To be safe, we should probably set 'order' explicitly in barplots or just map the labels.
    # Mapping labels is safer if we trust the current order.
    # Getting current labels from axes[2]

    # A safer way is to create a new column 'Neighborhood' and plot that directly.
    zdf['Neighborhood'] = zdf['Zip'].apply(get_neighborhood_label)

    # Let's replot with Neighborhood on x-axis to be cleaner and safer
    axes[0].clear()
    sns.barplot(data=zdf,
                x='Neighborhood',
                y='Sqft',
                hue='Neighborhood',
                legend=False,
                ax=axes[0],
                estimator='mean',
                errorbar=None,
                palette='Blues_d')
    axes[0].set_title('Average Square Footage by Neighborhood')
    axes[0].set_ylabel('Sq Ft')
    axes[0].tick_params(labelbottom=False)

    axes[1].clear()
    sns.barplot(data=zdf,
                x='Neighborhood',
                y='Beds',
                hue='Neighborhood',
                legend=False,
                ax=axes[1],
                estimator='mean',
                errorbar=None,
                palette='Greens_d')
    axes[1].set_title('Average Beds by Neighborhood')
    axes[1].set_ylabel('Beds')
    axes[1].tick_params(labelbottom=False)

    axes[2].clear()
    sns.barplot(data=zdf,
                x='Neighborhood',
                y='Baths',
                hue='Neighborhood',
                legend=False,
                ax=axes[2],
                estimator='mean',
                errorbar=None,
                palette='Reds_d')
    axes[2].set_title('Average Baths by Neighborhood')
    axes[2].set_ylabel('Baths')
    axes[2].set_xlabel('Neighborhood')
    plt.xticks(rotation=45, ha='right')

    filename = 'plots/zip_code_features.png'
    plt.tight_layout()
    plt.savefig(filename, dpi=300)
    plt.close()
    plot_files.append(filename)

  return plot_files


def create_report_content(df: pd.DataFrame, total_stats: Dict[str, Any],
                          plot_files: List[str]) -> str:
  """Generates the Markdown report content."""
  lines = []

  # Helper to get safe counts
  parsed_count = total_stats.get('emails_parsed', 0)
  cache_count = total_stats.get('cache_total', 0)
  db_count = df.shape[0]

  # Executive Summary & Coverage
  lines.append("### Latest Data Summary\n")
  lines.append(
      f"Generated on: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n\n")

  lines.append("#### Data Coverage\n")
  lines.append(
      f"- **Total Emails Cached**: **{cache_count}** (Source: `.email_cache.tsv`)\n"
  )
  lines.append(
      f"- **Total Emails Parsed**: **{parsed_count}** (Processed this run)\n")
  lines.append(
      f"- **Total Listings in Database**: **{db_count}** (Unique records in `housing_database.tsv`)\n"
  )
  lines.append(f"- **Parsing Errors**: **{total_stats.get('errors', 0)}**\n\n")

  # Market Visualizations
  if plot_files:
    lines.append("### Market Visualizations\n\n")

    # Define preferred order
    plot_order = [
         'categorical_pies.png',
         'monthly_volume.png',
         'price_trends_time_series.png',
         'price_dist.png',
         'price_vs_sqft.png',
         'pps_by_zip.png',
         'price_distribution_by_zip.png',
         'zip_code_features.png'
     ]
    name_map = {os.path.basename(p): p for p in plot_files}

    for name in plot_order:
      if name in name_map:
        p_path = name_map[name]
        readable_name = name.replace('.png', '').replace('_', ' ').title()
        lines.append(f"#### {readable_name}\n")
        lines.append(f"![{readable_name}]({p_path})\n\n")

    # Add any remaining plots not in the explicit list
    for p_path in plot_files:
      if os.path.basename(p_path) not in plot_order:
        val_name = os.path.basename(p_path).replace('.png',
                                                    '').replace('_',
                                                                ' ').title()
        lines.append(f"#### {val_name}\n")
        lines.append(f"![{val_name}]({p_path})\n\n")

  lines.append("### Parsing Statistics\n")
  total_props = total_stats.get('properties_found', 0)
  if total_props == 0:
    total_props = 1

  def pct(count):
    return f"({(count / total_props) * 100:.1f}%)"

  lines.append(
      f"- **Total Emails Parsed**: {total_stats.get('emails_parsed', 0)}\n")
  lines.append(
      f"- **Total Unique Properties Extracted**: {total_stats.get('properties_found', 0)}\n"
  )

  fields = [('Missing Price', 'missing_price'), ('Missing Beds',
                                                 'missing_beds'),
            ('Missing Baths', 'missing_baths'),
            ('Missing Sqft', 'missing_sqft'),
            ('Missing Listing Link', 'missing_link'),
            ('Missing City', 'missing_city'), ('Missing Zip', 'missing_zip'),
            ('Missing Type', 'missing_type'),
            ('Missing Address', 'missing_address'),
            ('Missing Status', 'missing_status'),
            ('Missing Open House', 'missing_open_house'),
            ('Missing Builder', 'missing_builder')]
  for label, key in fields:
    val = total_stats.get(key, 0)
    lines.append(f"- **{label}**: {val} {pct(val)}\n")
  lines.append("\n")

  lines.append("### Dataset Overview\n")
  lines.append(f"- **Total Rows**: {df.shape[0]}\n")
  lines.append(f"- **Total Columns**: {df.shape[1]}\n\n")

  # Data Summary
  clean_df = df.drop(columns=['Listing_Link', 'Email_Subject'], errors='ignore')

  # Ensure numeric columns
  numeric_cols = ['Price', 'Beds', 'Baths', 'Sqft']
  for col in numeric_cols:
    if col in clean_df.columns:
      clean_df[col] = pd.to_numeric(clean_df[col], errors='coerce')

  if 'Price' in clean_df.columns and 'Sqft' in clean_df.columns:
    clean_df['Price_Per_Sqft'] = clean_df['Price'] / clean_df['Sqft']

  numeric_df = clean_df.select_dtypes(include=['number'])
  if not numeric_df.empty:
    lines.append("#### Numerical Features\n")
    stats = numeric_df.describe(percentiles=[0.25, 0.5, 0.75]).T
    stats['median'] = numeric_df.median()
    lines.append(stats.round(2).to_markdown())
    lines.append("\n\n")

  categorical_df = clean_df.select_dtypes(exclude=['number'])
  if not categorical_df.empty:
    cat_desc = categorical_df.describe().fillna('')
    cat_desc = cat_desc.drop(['top', 'freq'], errors='ignore')
    lines.append("#### Categorical Features\n")
    lines.append(cat_desc.T.to_markdown())
    lines.append("\n\n")

  if 'Property_Type' in clean_df.columns:
    lines.append("### Property Type Distribution\n")
    type_counts: pd.Series = clean_df['Property_Type'].value_counts()
    type_pcts: pd.Series = clean_df['Property_Type'].value_counts(
        normalize=True) * 100
    type_summary = pd.DataFrame({
        'Count': type_counts,
        'Percent': type_pcts.round(1).apply(lambda x: f"{x}%")
    })
    lines.append(type_summary.to_markdown())
    lines.append("\n\n")

  if 'Zip' in clean_df.columns:
    lines.append("### Top 10 Zip Codes\n")
    top_zips = clean_df['Zip'].value_counts().head(10).reset_index()
    top_zips.columns = pd.Index(['Zip Code', 'Count'])
    top_zips['Zip Code'] = top_zips['Zip Code'].astype(int)

    # Add Neighborhood Name
    top_zips['Neighborhood'] = top_zips['Zip Code'].apply(
        lambda z: ZIP_NEIGHBORHOOD_MAP.get(z, 'Unknown'))

    # Reorder columns
    top_zips = top_zips[['Zip Code', 'Neighborhood', 'Count']]

    zip_table = top_zips.to_markdown(index=False)
    lines.append(f"{zip_table}\n\n")

  return "".join(lines)


def inject_report_into_readme(report_content: str, readme_path='README.md'):
  """Injects the generated report content into the README.md file."""
  if not os.path.exists(readme_path):
    logging.warning("%s not found. Skipping README update.", readme_path)
    return

  with open(readme_path, 'r', encoding='utf-8') as f:
    content = f.read()

  start_marker = "<!-- REPORT_START -->"
  end_marker = "<!-- REPORT_END -->"

  if start_marker in content and end_marker in content:
    pattern = re.compile(f"{re.escape(start_marker)}.*?{re.escape(end_marker)}",
                         re.DOTALL)
    new_section = f"{start_marker}\n{report_content}\n{end_marker}"
    new_content = pattern.sub(new_section, content)

    with open(readme_path, 'w', encoding='utf-8') as f:
      f.write(new_content)
    logging.info("Successfully updated README.md with the latest report.")
  else:
    logging.warning("Markers %s and %s not found in %s.", start_marker,
                    end_marker, readme_path)


if __name__ == "__main__":
  logging.basicConfig(level=logging.INFO,
                      format='%(asctime)s - %(levelname)s - %(message)s')
  input_csv = 'housing_database.tsv'
  if os.path.exists(input_csv):
    logging.info("Loading data from %s...", input_csv)
    df = pd.read_csv(input_csv, sep='\t')

    logging.info("Generating plots...")
    plot_files = generate_plots(df)

    logging.info("Generating report text...")
    # Dummy stats for standalone report generation
    dummy_stats = {'emails_parsed': 0, 'properties_found': df.shape[0]}
    report = create_report_content(df, dummy_stats, plot_files)

    logging.info("Injecting report into README.md...")
    inject_report_into_readme(report)
