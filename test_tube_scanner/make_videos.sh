#!/bin/bash

# Génère 24 vidéos pour simuler le balayage d'un multi-puit de 6x24 
#   A1..A6, B1..B6, C1..C6, D1..D6
#  

PATH="./media/simulation"
default_width=1000      # px
default_height=1000     # px
default_diameter=16.0   # mm

declare -A arguments=(
    # key  count length width fps duration seed bg-color arena-color arena-border shadow-color body-color body-dark body-light head-color thresh-immobile thresh-mobile thigmotaxis photo-mode photo-strength photo-x photo-y photo-sine-freq photo-radius chemo-strength chemo-x chemo-y chemo-radius avoid-strength avoid-radius aggreg-strength aggreg-radius chem-repulsion chem-decay
    ["A1"]="3     0.40   0.30   5  60        64  #EBEBEB  #FAFAFA     #8C8C8C      #C8C8C8      #A5A5A5    #373737   #D2D2D2    #828282    0.2             1.5           0.45        none       0.50           0.50    0.50    0.10            0.30         0.0            0.70    0.70    2.0          1.0            3.0          0.0             6.0           0.0            0.95"
    ["A2"]="1     0.42   0.32   5  60        96  #EBEBEB  #FAFAFA     #8C8C8C      #C8C8C8      #A5A5A5    #373737   #D2D2D2    #828282    0.2             1.5           0.70        fixed      0.50           0.50    0.50    0.10            0.30         0.0            0.70    0.70    2.0          0.0            3.0          0.0             6.0           0.0            0.95"
    ["A3"]="1     0.50   0.40   5  60       128  #EBEBEB  #FAFAFA     #8C8C8C      #C8C8C8      #A5A5A5    #373737   #D2D2D2    #828282    0.2             1.5           0.70        radial     0.50           0.50    0.50    0.10            0.30         0.5            0.70    0.70    2.0          0.0            3.0          0.0             6.0           0.0            0.95"

)


for key in "${!arguments[@]}"; do
    args="${arguments[$key]}"
    read -r count length width fps duration seed bg_color arena_color arena_border shadow_color \
            body_color body_dark body_light head_color thresh_immobile thresh_mobile thigmotaxis \
            photo_mode photo_strength photo_x photo_y photo_sine_freq photo_radius chemo_strength chemo_x chemo_y chemo_radius \
            avoid_strength avoid_radius aggreg_strength aggreg_radius chem_repulsion chem_decay <<< "$args"
            
    echo "==== Exécution de $PATH/$key.mp4"
    
    ./planarian_sim.py --output "$PATH/$key.mp4" --default_width "$default_width" --default_height "$default_height" --default_diameter "$default_diameter"  --no-csv \
        --count "$count" --length "$length" --width "$width" --duration "$duration" --fps "$fps" --seed "$seed" \
        --bg-color "$bg_color" --arena-color "$arena_color" --arena-border "$arena_border" --shadow-color "$shadow_color" \
        --body-color "$body_color" --body-dark  "$body_dark" --body-light "$body_light" --head-color "$head_color" \
        --thresh-immobile "$thresh_immobile" --thresh-mobile "$thresh_mobile" --thigmotaxis "$thigmotaxis"  \
        --photo-mode "$photo_mode" --photo-strength "$photo_strength" --photo-x "$photo_x" --photo-y "$photo_y" --photo-sine-freq "$photo_sine_freq" --photo-radius "$photo_radius"  \
        --chemo-strength "$chemo_strength" --chemo-x "$chemo_x" --chemo-y "$chemo_y" --chemo-radius "$chemo_radius"  \
        --avoid-strength "$avoid_strength" --avoid-radius "$avoid_radius" --aggreg-strength "$aggreg_strength" --aggreg-radius "$aggreg_radius" \
        --chem-repulsion "$chem_repulsion" --chem-decay "$chem_decay"
done
