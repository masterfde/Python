import streamlit as st
import seaborn as sns
import matplotlib.pyplot as plt

sns.set_theme(style="whitegrid")

# Load Titanic dataset
titanic = sns.load_dataset("titanic")

st.title("Mr. Raj Kumar Master Meitei Seaborn Practice - Titanic Data Visualization App")

st.write("This is a simple app to visualize the Titanic dataset using Seaborn.")

# Function to create and display plots
def display_plot(title, plot_func):
    st.subheader(title)
    fig, ax = plt.subplots(figsize=(8, 6))
    plot_func(ax=ax)
    st.pyplot(fig)
    plt.close(fig)


# 1. Scatter Plot
def scatter_plot(ax):
    sns.scatterplot(
        data=titanic,
        x="age",
        y="fare",
        hue="survived",
        size="pclass",
        palette="deep",
        ax=ax
    )
    ax.set_title("Scatter Plot of Passenger Age vs Fare")


# 2. Line Plot
def line_plot(ax):
    sns.lineplot(
        data=titanic,
        x="pclass",
        y="fare",
        hue="sex",
        marker="o",
        ax=ax
    )
    ax.set_title("Average Fare by Passenger Class and Gender")


# 3. Bar Plot
def bar_plot(ax):
    sns.barplot(
        data=titanic,
        x="class",
        y="survived",
        hue="sex",
        palette="muted",
        ax=ax
    )
    ax.set_title("Survival Rate by Passenger Class and Gender")
    ax.set_ylabel("Survival Rate")


# 4. Box Plot
def box_plot(ax):
    sns.boxplot(
        data=titanic,
        x="class",
        y="age",
        hue="survived",
        palette="Set2",
        ax=ax
    )
    ax.set_title("Age Distribution by Class and Survival Status")


# 5. Violin Plot
def violin_plot(ax):
    sns.violinplot(
        data=titanic,
        x="class",
        y="age",
        hue="sex",
        split=True,
        palette="pastel",
        ax=ax
    )
    ax.set_title("Age Distribution by Passenger Class and Gender")


# 6. Count Plot
def count_plot(ax):
    sns.countplot(
        data=titanic,
        x="class",
        hue="survived",
        palette="dark",
        ax=ax
    )
    ax.set_title("Passenger Count by Class and Survival Status")


# 7. Regression Plot
def reg_plot(ax):
    sns.regplot(
        data=titanic,
        x="age",
        y="fare",
        scatter_kws={"s": 50},
        line_kws={"color": "red"},
        ax=ax
    )
    ax.set_title("Regression Plot of Passenger Age vs Fare")


# 8. Histogram Plot
def hist_plot(ax):
    sns.histplot(
        data=titanic,
        x="age",
        bins=20,
        kde=True,
        color="blue",
        ax=ax
    )
    ax.set_title("Histogram of Passenger Age with KDE")


# 9. Strip Plot
def strip_plot(ax):
    sns.stripplot(
        data=titanic,
        x="class",
        y="fare",
        hue="sex",
        jitter=True,
        palette="Set1",
        ax=ax
    )
    ax.set_title("Fare Distribution by Passenger Class and Gender")


# 10. KDE Plot
def kde_plot(ax):
    sns.kdeplot(
        data=titanic,
        x="age",
        hue="sex",
        fill=True,
        palette="tab10",
        ax=ax
    )
    ax.set_title("Passenger Age Density by Gender")


# Display all plots
display_plot("Scatter Plot", scatter_plot)
display_plot("Line Plot", line_plot)
display_plot("Bar Plot", bar_plot)
display_plot("Box Plot", box_plot)
display_plot("Violin Plot", violin_plot)
display_plot("Count Plot", count_plot)
display_plot("Regression Plot", reg_plot)
display_plot("Histogram Plot", hist_plot)
display_plot("Strip Plot", strip_plot)
display_plot("KDE Plot", kde_plot)
