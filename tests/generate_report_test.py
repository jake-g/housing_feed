import os
from unittest.mock import MagicMock
from unittest.mock import mock_open
from unittest.mock import patch

import pandas as pd
import pytest

import generate_report


@pytest.fixture
def sample_data():
  df = pd.DataFrame({
      'Date': ['2023-01-01', '2023-02-01', '2023-03-01'],
      'Price': [500000, 600000, 550000],
      'Zip': [98101, 98102, 98101],
      'Property_Type': ['House', 'Condo', 'House'],
      'Sqft': [1500, 1000, 1600]
  })
  stats = {
      'properties_found': 3,
      'emails_parsed': 1,
      'missing_price': 0,
      'errors': 0
  }
  return df, stats

@patch('generate_report.plt')
@patch('generate_report.sns')
def test_generate_plots(mock_sns, mock_plt, sample_data):
  df, _ = sample_data
  mock_figure = MagicMock()
  mock_axes = MagicMock()

  # Create individual mock axes
  ma1, ma2, ma3 = MagicMock(), MagicMock(), MagicMock()

  # Configure pie return values
  ma1.pie.return_value = (MagicMock(), MagicMock(), MagicMock())
  ma2.pie.return_value = (MagicMock(), MagicMock(), MagicMock())
  ma3.pie.return_value = (MagicMock(), MagicMock(), MagicMock())

  # Mock flatten to return list of axes
  mock_axes.flatten.return_value = [ma1, ma2, ma3]
  mock_plt.subplots.return_value = (mock_figure, mock_axes)
  mock_plt.figure.return_value = mock_figure

  plot_files = generate_report.generate_plots(df)

  assert len(plot_files) > 0
  assert mock_plt.savefig.called
  assert mock_plt.close.called

def test_create_report_content(sample_data):
  df, stats = sample_data
  content = generate_report.create_report_content(df, stats, plot_files=['plots/test.png'])

  assert "### Latest Data Summary" in content
  assert "Total Listings in Database**: **3" in content
  assert "### Market Visualizations" in content
  assert "plots/test.png" in content
  assert "98101" in content

def test_inject_report_into_readme():
  readme_content = """# Project\n\n<!-- REPORT_START -->\nOld Report\n<!-- REPORT_END -->\n\nEnd"""
  report_content = "New Report Content"

  with patch("builtins.open", mock_open(read_data=readme_content)) as mock_file:
    with patch("os.path.exists", return_value=True):
      generate_report.inject_report_into_readme(report_content)

      # Verify write
      handle = mock_file()
      # Combine all writes
      written_content = "".join(call.args[0] for call in handle.write.call_args_list)

      assert "<!-- REPORT_START -->" in written_content
      assert "New Report Content" in written_content
      assert "<!-- REPORT_END -->" in written_content
      assert "Old Report" not in written_content
