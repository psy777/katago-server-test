import json
import argparse

def parse_katago_analysis(filename):
    """
    Parses a Katago analysis JSON file, sorts all moves by playSelectionValue and then by visits,
    and returns the fully ranked list.
    """
    try:
        with open(filename, 'r') as f:
            content = f.read()
            # Find the start of the JSON object to handle files with leading text
            json_start_index = content.find('{')
            if json_start_index == -1:
                print("Error: No JSON object found in the file.")
                return []
            
            # Slice the string to get only the JSON part
            json_content = content[json_start_index:]
            data = json.loads(json_content)

        # [cite_start]The moves are in the 'moveInfos' key [cite: 1]
        if 'moveInfos' not in data or not data['moveInfos']:
            print("Error: No 'moveInfos' found in the JSON data.")
            return []
        
        move_infos = data['moveInfos']

        # Sort by playSelectionValue (desc) and then by visits (desc)
        # Using .get() with a default value adds robustness for entries that might be missing a key
        sorted_moves = sorted(
            move_infos, 
            key=lambda x: (x.get('playSelectionValue', 0), x.get('visits', 0)), 
            reverse=True
        )

        return sorted_moves

    except FileNotFoundError:
        print(f"Error: File not found: {filename}")
        return []
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON format in file: {filename}")
        return []
    except KeyError as e:
        print(f"Error: Missing expected key in JSON data: {e}")
        return []
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return []


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Parse a Katago analysis JSON file and return a ranked list of all moves.")
    parser.add_argument("filename", help="Path to the Katago analysis file.")
    args = parser.parse_args()

    ranked_moves = parse_katago_analysis(args.filename)

    if ranked_moves:
        print("Ranked Moves (sorted by playSelectionValue and visits):")
        # Add a header for the output table for clarity
        print(f"{'Rank':<5} {'Move':<10} {'PlaySelectionValue':<20} {'Visits':<10}")
        print("-" * 55)
        for i, move in enumerate(ranked_moves, 1):
            # Using .get() for safety in case a key is missing in some move objects
            move_val = move.get('move', 'N/A')
            psv = move.get('playSelectionValue', 'N/A')
            visits = move.get('visits', 'N/A')
            print(f"{i:<5} {move_val:<10} {psv:<20} {visits:<10}")
