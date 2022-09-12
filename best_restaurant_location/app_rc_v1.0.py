from dis import show_code
from http import server
from operator import le
from textwrap import shorten
import streamlit as st
import geopandas as gpd
from IPython.core.display import display, HTML
import folium
from streamlit_folium import folium_static
from sklearn.preprocessing import MinMaxScaler
import plotly.express as px
import numpy as np
import os
import pandas as pd
from scipy.spatial import ConvexHull
import plotly.graph_objects as go


st.markdown("""# Next Restaurant in Geneva
## Click on the Markers to get more information""")


# main dataframe with decreased columns
data = pd.read_csv('data/data_combined_v1.04.csv')\
    [['place_id',
    'name',
    'price_level_combined',
    'user_ratings_total',
    'combined_rating',
    'geometry.location.lat', 'geometry.location.lng',
    'combined_main_category',
    'sub_category',
    'district',
    'district_cluster',
    'combined_main_category_2']]

# dataframe contains coordinates for district clusters
df_cluster_centers = pd.read_csv('data/data_cluster_centers_v1.02.csv')

### Functions Start ###
def filter_data(data, rest_district, rest_category_main, rest_category):
    """
    Filters main dataframe based on district or restaurant selection
    FOR DROWDOWN MENUS
    Returns a filtered dataframe
    """
    if rest_district != 'All':
        data = data[data['district']==rest_district]

    if rest_category_main != 'All':
        data = data[data['combined_main_category_2']==rest_category_main]

    if rest_category != 'All':
        data = data[data['combined_main_category'].str.contains(rest_category)]

    return data.reset_index(drop=True)

def filter_data_scoring(data, rest_district, rest_category_main, rest_category):
    """
    Filters main dataframe based on district or restaurant selection
    FOR SCORING
    Returns a filtered dataframe
    """
    if rest_district != 'All':
        data = data[data['district']==rest_district]

    if rest_category_main != 'All':
        data = data[data['combined_main_category_2']==rest_category_main]

    if rest_category != 'All':
        data = data[data['combined_main_category'].str.contains(rest_category)]

    data = data.groupby(['district','district_cluster'])\
        [['place_id', 'user_ratings_total','combined_rating']]\
        .agg({'place_id':'count',
        'user_ratings_total':'mean',
        'combined_rating':'mean'})\
        .rename(columns={'place_id':f'{rest_category.lower()}_restaurants'})

    return data.reset_index()

def merge_data(data, rest_district, rest_category_main, rest_category):
    """
    Creates a merged data set based on filtering selections and
    returns the final data set before normalization and scoring
    """
    if rest_category == 'All':
        data = filter_data_scoring(data, rest_district, rest_category_main, rest_category)
    else:
        data = filter_data_scoring(data, rest_district, 'All', 'All')\
            .merge(
                filter_data_scoring(data, rest_district, rest_category_main, rest_category)\
                    .drop(columns=['district','user_ratings_total','combined_rating']),
                how='left',
                on='district_cluster')\
            .fillna(0)
    return data

def score_data(data, rest_district, rest_category_main, rest_category, score_com, score_pop, score_sat):
    """
    Normalizes merged data set and create a custom scoring
    """
    # create merged data set
    df_merged = merge_data(data, rest_district, rest_category_main, rest_category)

    # normalization
    scaler = MinMaxScaler()
    cols = df_merged.drop(columns=['district','district_cluster'])
    scaler.fit(cols)
    df_score = pd.DataFrame(scaler.transform(cols), columns=cols.columns+'_norm')

    # scoring

    if rest_category == 'All':
        score_tot = score_com + score_pop + score_sat
        df_score['score'] = (score_com * (1-df_score['all_restaurants_norm'])\
                            +score_pop * df_score['user_ratings_total_norm']\
                            +score_sat * (1-df_score['combined_rating_norm']))\
                            / score_tot

    else:
        score_tot = 2 * score_com + score_pop + score_sat
        df_score['score'] = (score_com * (1-df_score['all_restaurants_norm'])\
                            +score_pop * df_score['user_ratings_total_norm']\
                            +score_sat * (1-df_score['combined_rating_norm'])
                            +score_com * (1-df_score[f'{rest_category.lower()}_restaurants_norm']))\
                            / score_tot

    # create output data_set
    df_output = pd.concat([df_merged, df_score], axis=1)\
        .merge(df_cluster_centers, how='left', on='district_cluster')
    return df_output

def pick_location(data, rest_district, rest_category_main, rest_category, score_com, score_pop, score_sat):
    """
    Select best / worst location based on custom scoring
    """
    if rest_district == 'All':
        n = 5
    else:
        n = 1

    best_location = score_data(data, rest_district, rest_category_main, rest_category, score_com, score_pop, score_sat)\
        .nlargest(n, 'score').reset_index(drop=True)
    worst_location = score_data(data, rest_district, rest_category_main, rest_category, score_com, score_pop, score_sat)\
        .nsmallest(n, 'score').reset_index(drop=True)

    return best_location, worst_location

def create_convexhull_polygon(map_object, list_of_points, layer_name, line_color, fill_color, weight, text):

    # Since it is pointless to draw a convex hull polygon around less than 3 points check len of input
    if len(list_of_points) > 2:

        # Create the convex hull using scipy.spatial
        form = [list_of_points[i] for i in ConvexHull(list_of_points).vertices]

        # Create feature group, add the polygon and add the feature group to the map
        fg = folium.FeatureGroup(name=layer_name)
        fg.add_child(folium.vector_layers.Polygon(locations=form, color=line_color, fill_color=fill_color,
                                                  weight=weight, stroke=False, popup=(folium.Popup(text))))
        map_object.add_child(fg)

    return (map_object)

#filter and search the restaurants
def search(df, category):
  search = lambda x:True if category.lower() in x.lower() else False
  venues = df[df['combined_main_category'].apply(search)].reset_index(drop='index')
  venues_lat_long = list(zip(venues['geometry.location.lat'], venues['geometry.location.lng']))
  return venues

### Functions END ###

# this is just a test on anea's idea, not the final categorization
dict_rest = {
    'All':['All'],
    'European': ['All', 'European', 'French', 'Italian', 'Swiss', 'Portuguese', 'Spanish'],
    'Asian':['All', 'Japanese', 'Chinese', 'Thai', 'Indian', 'Other Asian'],
    'Middle Eastern & African': ['All', 'Lebanese', 'Turkish', 'Other Middle Eastern', 'African'],
    'American': ['All', 'American', 'South American', 'Mexican', 'Hawaiian'],
    'General': ['All', 'Restaurant', 'Bar / Pub / Bistro', 'Café'],
    'Fast Food':['All', 'Pizza', 'Hamburger', 'Chicken', 'Snacks / Take Away'],
    'Steakhouse / Barbecue / Grill': ['Steakhouse / Barbecue / Grill'],
    'Seafood': ['Seafood'],
    'Vegan / Vegetarian / Salad': ['Vegan / Vegetarian / Salad'],
    'All Other': ['All Other']}

list_district = [
    'All',
    'Saint-Jean Charmilles',
    'Bâtie - Acacias',
    'Servette Petit-Saconnex',
    'Jonction - Plainpalais',
    'Eaux-Vives - Lac',
    'Grottes Saint-Gervais',
    'Pâquis Sécheron',
    'La Cluse - Philosophes',
    'Cité-Centre',
    'Champel']

# choose the categories
st.sidebar.write('**Select the type of cuisine 🍽**')
rest_category_main = st.sidebar.selectbox("Main Restaurant Category", dict_rest.keys())
rest_category = st.sidebar.selectbox("Sub Restaurant Category", dict_rest[rest_category_main])
rest_district = st.sidebar.selectbox("Area", list_district)

st.sidebar.text("")
st.sidebar.write('**Select Scoring Criteria 🎯**')
score_com = st.sidebar.slider('Number of Competitors', min_value=0, max_value=4, value=2, step=1)
score_pop = st.sidebar.slider('Area Popularity', min_value=0, max_value=4, value=2, step=1)
score_sat = st.sidebar.slider('Customer Satisfaction', min_value=0, max_value=4, value=2, step=1)


#create basic maps to be filled
geneva_1 = folium.Map(location=[46.20494053262858, 6.142254182958967], zoom_start=13.4, tiles='cartodbpositron')
geneva_2 = folium.Map(location=[46.20494053262858, 6.142254182958967], zoom_start=13.4, tiles='cartodbpositron')
geneva_3 = folium.Map(location=[46.20494053262858, 6.142254182958967], zoom_start=13.4, tiles='cartodbpositron')
geneva_4 = folium.Map(location=[46.20494053262858, 6.142254182958967], zoom_start=13.4, tiles='cartodbpositron')


data['combined_main_category'].fillna(value='not defined', inplace=True) # not sure this is needed anymore

df = filter_data(data, rest_district, rest_category_main, rest_category)


### Section for Overview Maps ###
marker_cluster = folium.plugins.MarkerCluster().add_to(geneva_1)

if len(df)!=0:
    for i,row in df.iterrows():
        folium.Marker(
            location=[row['geometry.location.lat'], row['geometry.location.lng']],
            popup=[row]
            ).add_to(marker_cluster)

# folium.LayerControl().add_to(geneva_1) # this gives a weird layer selection, so removed for the moment - Burak

group0 = folium.FeatureGroup(name='<span style=\\"color: red;\\">rating below 3.0</span>')
group1 = folium.FeatureGroup(name='<span style=\\"color: orange;\\">rating between 3.0 and 4.0</span>')
group2 = folium.FeatureGroup(name='<span style=\\"color: lightgreen;\\">rating between 4 and 4.5</span>')
group3 = folium.FeatureGroup(name='<span style=\\"color: green;\\">rating above 4.5</span>')
for i,row in df.iterrows():
    if row['combined_rating']<3.0:
        folium.CircleMarker(location=[row['geometry.location.lat'], row['geometry.location.lng']],radius=4, color='red',fillColor='red', fill=True,
                            popup=folium.Popup(f"{row['name']}, {row['combined_rating']}", max_width='100')).add_to(group0)
    elif row['combined_rating']>=3.0 and row['combined_rating']<4.0:
        folium.CircleMarker(location=[row['geometry.location.lat'], row['geometry.location.lng']], radius=4, color='orange',fillColor='orange', fill=True, popup=[row['name'], row['combined_rating']] ).add_to(group1)
    elif row['combined_rating']>=4.0 and row['combined_rating']<4.5:
        folium.CircleMarker(location=[row['geometry.location.lat'], row['geometry.location.lng']], radius=4, color='lightgreen',fillColor='lightgreen', fill=True, popup=[row['name'], row['combined_rating']] ).add_to(group2)
    elif row['combined_rating']>=4.5:
        folium.CircleMarker(location=[row['geometry.location.lat'], row['geometry.location.lng']], radius=4, color='green',fillColor='green', fill=True, popup=[row['name'], row['combined_rating']] ).add_to(group3)

group0.add_to(geneva_3)
group1.add_to(geneva_3)
group2.add_to(geneva_3)
group3.add_to(geneva_3)
folium.map.LayerControl('topright', collapsed=False).add_to(geneva_3)

group0 = folium.FeatureGroup(name='<span style=\\"color: red;\\">$$$$</span>')
group1 = folium.FeatureGroup(name='<span style=\\"color: orange;\\">$$$-$$$$</span>')
group2 = folium.FeatureGroup(name='<span style=\\"color: green;\\">$-$$</span>')

for i,row in df.iterrows():
    if row['price_level_combined']<3:
        folium.CircleMarker(location=[row['geometry.location.lat'], row['geometry.location.lng']],radius=4, color='green',fillColor='green', fill=True, popup=[row['name'], row['price_level_combined']]).add_to(group2)
    elif row['price_level_combined']<4 and row['price_level_combined']>=3:
        folium.CircleMarker(location=[row['geometry.location.lat'], row['geometry.location.lng']], radius=4, color='orange',fillColor='orange', fill=True, popup=[row['name'], row['price_level_combined']] ).add_to(group1)
    elif row['price_level_combined']>=4:
        folium.CircleMarker(location=[row['geometry.location.lat'], row['geometry.location.lng']], radius=4, color='red',fillColor='red', fill=True, popup=[row['name'], row['price_level_combined']] ).add_to(group0)

group0.add_to(geneva_2)
group1.add_to(geneva_2)
group2.add_to(geneva_2)
folium.map.LayerControl('topright', collapsed=False).add_to(geneva_2)


group0 = folium.FeatureGroup(name='<span style=\\"color: red;\\">less then 50 ratings</span>')
group1 = folium.FeatureGroup(name='<span style=\\"color: orange;\\">between 50 and 149 ratings</span>')
group2 = folium.FeatureGroup(name='<span style=\\"color: lightgreen;\\">between 150 and 199 ratings</span>')
group3 = folium.FeatureGroup(name='<span style=\\"color: green;\\">more then 200 rantings ratings</span>')
for i,row in df.iterrows():
    if row['user_ratings_total']<50.0:
        folium.CircleMarker(location=[row['geometry.location.lat'], row['geometry.location.lng']],radius=4, color='red',fillColor='red', fill=True, popup=[row['name'], row['user_ratings_total']]).add_to(group0)
    elif row['user_ratings_total']>=50.0 and row['user_ratings_total']<150.0:
        folium.CircleMarker(location=[row['geometry.location.lat'], row['geometry.location.lng']], radius=4, color='orange',fillColor='orange', fill=True, popup=[row['name'], row['user_ratings_total']] ).add_to(group1)
    elif row['user_ratings_total']>=150.0 and row['user_ratings_total']<200.0:
        folium.CircleMarker(location=[row['geometry.location.lat'], row['geometry.location.lng']], radius=4, color='lightgreen',fillColor='lightgreen', fill=True, popup=[row['name'], row['user_ratings_total']] ).add_to(group2)
    elif row['user_ratings_total']>=200.0:
        folium.CircleMarker(location=[row['geometry.location.lat'], row['geometry.location.lng']], radius=4, color='green',fillColor='green', fill=True, popup=[row['name'], row['user_ratings_total']] ).add_to(group3)
group0.add_to(geneva_4)
group1.add_to(geneva_4)
group2.add_to(geneva_4)
group3.add_to(geneva_4)

folium.map.LayerControl('topright', collapsed=False).add_to(geneva_4)

# display the maps
tab1, tab2, tab3, tab4 = st.tabs(["Overview", "Price Level", "Review Scores", "Number of Reviews"])

with tab1:
    #st.header("## Check the best and worst restaurants based on general info")
    folium_static(geneva_1)

with tab2:
    #st.markdown("## Check the best and worst restaurants based on Price Level")
    folium_static(geneva_2)

with tab3:
    #st.header("## Check the best and worst restaurants based on Review Score")
    folium_static(geneva_3)

with tab4:
    #st.header("## Check the best and worst restaurants based on Number of Reviews")
    folium_static(geneva_4)


with st.expander("See more information"):
    st.write(f'In Geneva there are **{len(df)}** restaurants belonging to the selected category')
    st.write(f'Their general review score is: {df.combined_rating.median()}📈')
    st.write(f'Their general price level is: {round(df.price_level_combined.mean())}💲')


districts = data['district'].unique() # is this required?

#geneva_zip_codes.fit_bounds([venues[['geometry.location.lat'][1]], venues['geometry.location.lng'][1]])

### MAP Best / Worst Locations START ###
best_locations = pick_location(data, rest_district, rest_category_main, rest_category, score_com, score_pop, score_sat)[0]
worst_locations = pick_location(data, rest_district, rest_category_main, rest_category, score_com, score_pop, score_sat)[1]

geneva_5 = folium.Map(location=[46.20494053262858, 6.142254182958967], zoom_start=13.6, tiles='cartodbpositron')

for i, row in best_locations.iterrows():
    cluster = row['district_cluster']
    list_of_points = data[data['district_cluster']==cluster][['geometry.location.lat','geometry.location.lng']].to_numpy()
    create_convexhull_polygon(geneva_5, list_of_points, layer_name='Best Locations',
                        line_color='green',
                        fill_color='green',
                        weight=1,
                        text=f"{row['district_cluster']}")

for i, row in worst_locations.iterrows():
    cluster = row['district_cluster']
    list_of_points = data[data['district_cluster']==cluster][['geometry.location.lat','geometry.location.lng']].to_numpy()
    create_convexhull_polygon(geneva_5, list_of_points, layer_name='Best Locations',
                        line_color='red',
                        fill_color='red',
                        weight=1,
                        text=f"{row['district_cluster']}")

folium_static(geneva_5)
