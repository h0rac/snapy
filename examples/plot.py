import pandas as pd
import matplotlib.pyplot as plt

read_file = pd.read_csv (r'coords.csv')
read_file.to_excel (r'coords.xlsx', index = None, header=True)


def plot_data(data):
  color = "green"
  colors = []
  rows = list(data['X'])
  columns = list(data['Y'])
  results = list(data['RESULT'])
  plt.figure(figsize=(15,15))
  plt.style.use('seaborn')
  plt.title("Chip plot")
  for item in results:
    if item == 1:
      colors.append("red")
    else:
      colors.append("orange")
 
  plt.scatter(rows,columns,marker="o",s=20, c=colors)
  plt.show()


data = pd.read_excel("coords.xlsx")
plot_data(data)