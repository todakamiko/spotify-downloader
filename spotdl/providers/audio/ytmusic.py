"""
YTMusic module for downloading and searching songs.
"""

from typing import Any, Dict, List, Optional

from ytmusicapi import YTMusic
from slugify import slugify
from rapidfuzz import fuzz

from spotdl.providers.audio.base import AudioProvider
from spotdl.types import Song
from spotdl.utils.formatter import (
    create_song_title,
    parse_duration,
    create_search_query,
)


class YouTubeMusic(AudioProvider):
    """
    YouTube Music audio provider class
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """
        Initialize the YouTube Music API

        ### Arguments
        - args: Arguments passed to the `AudioProvider` class.
        - kwargs: Keyword arguments passed to the `AudioProvider` class.
        """

        super().__init__(*args, **kwargs)
        self.client = YTMusic()

    def search(self, song: Song) -> Optional[str]:
        """
        Search for a song on YouTube Music.

        ### Arguments
        - song: The song to search for.

        ### Returns
        - The url of the best match or None if no match was found.
        """

        if self.search_query:
            search_query = create_search_query(
                song, self.search_query, False, None, True
            )
        else:
            # search for song using isrc if it's available
            if song.isrc:
                isrc_results = self.get_results(
                    song.isrc, filter="songs", ignore_spelling=True
                )

                if len(isrc_results) == 1:
                    isrc_result = self.order_results([isrc_results[0]], song, True)
                    if len(isrc_result) == 1:
                        isrc_link, isrc_score = isrc_result.popitem()

                        if isrc_score > 90:
                            # print(f"# RETURN URL - {isrc_link} - isrc score")
                            return isrc_link

                        # print(f"# no match found for isrc {song.name} - {song.isrc}")

            search_query = create_song_title(song.name, song.artists).lower()

        # Query YTM by songs only first, this way if we get correct result on the first try
        # we don't have to make another request
        song_results = self.get_results(
            search_query, filter="songs", ignore_spelling=True
        )

        if self.filter_results:
            # Order results
            songs = self.order_results(song_results, song)
        else:
            songs = {}
            if len(song_results) > 0:
                songs = {song_results[0]["link"]: 100}

        # song type results are always more accurate than video type,
        # so if we get score of 80 or above
        # we are almost 100% sure that this is the correct link
        if len(songs) != 0:
            # get the result with highest score
            best_result = max(songs, key=lambda k: songs[k])

            if songs[best_result] >= 80:
                # print(f"# RETURN URL - {best_result} - song >= 80")
                return best_result

        # We didn't find the correct song on the first try so now we get video type results
        # add them to song_results, and get the result with highest score
        video_results = self.get_results(
            search_query, filter="videos", ignore_spelling=True
        )

        if self.filter_results:
            # Order video results
            videos = self.order_results(video_results, song)
        else:
            videos = {}
            if len(video_results) > 0:
                videos = {video_results[0]["link"]: 100}

        # Merge songs and video results
        results = {**songs, **videos}

        # No matches found
        if not results:
            return None

        result_items = list(results.items())

        # Sort results by highest score
        sorted_results = sorted(result_items, key=lambda x: x[1], reverse=True)

        last_simlar_index = 0
        best_score = sorted_results[0][1]

        # Get few results with score close to the best score
        for index, (_, score) in enumerate(sorted_results):
            if (best_score - score) > 8:
                last_simlar_index = index
                break

        # Get the best results from the similar results
        best_results = sorted_results[:last_simlar_index]

        # If we have only one result, return it
        if len(best_results) == 1:
            # print(f"# RETURN URL - {sorted_results[0][0]} - sorted, no best results")
            return sorted_results[0][0]

        # print(f"# best results: {best_results}")

        # If we have more than one result,
        # return the one with the highest score
        # and most views
        views_data = [
            self.client.get_song(best_result[0].split("=")[1])["videoDetails"][
                "viewCount"
            ]
            for best_result in best_results
        ]

        # print(f"# views_data: {views_data}")

        best_result = best_results[views_data.index(str(max(map(int, views_data))))]

        # print(f"# RETURN URL - {best_result[0]} - sorted, best results")
        return best_result[0]

    def get_results(self, search_term: str, **kwargs) -> List[Dict[str, Any]]:
        """
        Get results from YouTube Music API and simplify them

        ### Arguments
        - search_term: The search term to search for.
        - kwargs: other keyword arguments passed to the `YTMusic.search` method.

        ### Returns
        - A list of simplified results (dicts)
        """

        results = self.client.search(search_term, **kwargs)

        # Simplify results
        simplified_results = []
        for result in results:
            if result is None or result.get("videoId") is None:
                continue

            artists_names = list(map(lambda a: a["name"], result["artists"]))

            simplified_results.append(
                {
                    "name": result["title"],
                    "type": result["resultType"],
                    "link": (
                        f'https://{"music" if result["resultType"] == "song" else "www"}'
                        f".youtube.com/watch?v={result['videoId']}"
                    ),
                    "album": result.get("album", {}).get("name")
                    if result.get("album")
                    else None,
                    "duration": parse_duration(result.get("duration")),
                    "artists": ", ".join(artists_names),
                    "artists_list": artists_names,
                }
            )

        return simplified_results

    def order_results(
        self, results: List[Dict[str, Any]], song: Song, is_isrc: bool = False
    ) -> Dict[str, Any]:
        """
        Filter results based on the song's metadata.

        ### Arguments
        - results: The results to filter.
        - song: The song to filter by.
        - is_isrc: Whether the results are from an isrc search.

        ### Returns
        - A dict of filtered results.
        """

        # Slugify some variables
        slug_song_name = slugify(song.name)
        slug_song_album_name = slugify(song.album_name)
        slug_song_main_artist = slugify(song.artist)
        slug_song_artists = slugify(", ".join(song.artists))
        slug_song_title = slugify(
            create_song_title(song.name, song.artists)
            if not self.search_query
            else create_search_query(song, self.search_query, False, None, True)
        )

        # DEBUG CODE
        # print(f"#############################")
        # print(f"song.name: {song.name}")
        # print(f"song.album_name: {song.album_name}")
        # print(f"song.artist: {song.artist}")
        # print(f"song.artists: {song.artists}")
        # print(f"song.isrc: {song.isrc}")
        # print(f"song.duration: {song.duration}")
        # print(f"slug_song_name: {slug_song_name}")
        # print(f"slug_song_album_name: {slug_song_album_name}")
        # print(f"slug_song_main_artist: {slug_song_main_artist}")
        # print(f"slug_song_artists: {slug_song_artists}")
        # print(f"slug_song_title: {slug_song_title}")
        # print(f"slug_song_duration: {song.duration}")
        # print(f"slug_song_artists: {slug_song_artists}")
        # print(f"#############################")

        # Assign an overall avg match value to each result
        links_with_match_value = {}
        for result in results:
            # Slugify result title
            slug_result_name = slugify(result["name"])
            slug_result_artists = slugify(result["artists"])
            slug_result_album = (
                slugify(result["album"]) if result.get("album") else None
            )

            # check for common words in result name
            sentence_words = slug_song_name.split("-")
            common_word = any(
                word != "" and word in slug_result_name for word in sentence_words
            )

            # print("-----------------------------")
            # print(f"sentence_words: {sentence_words}")
            # print(f"common_word: {common_word}")
            # print(f"result link: {result['link']}")
            # print(f"result type: {result['type']}")
            # print(f"result duration: {result['duration']}")
            # print(f"result artists_list: {result['artists_list']}")
            # print(f"slug_result_name: {slug_result_name}")
            # print(f"slug_result_artists: {slug_result_artists}")
            # print(f"slug_result_album: {slug_result_album}")
            # print("-----------------------------")

            # skip results that have no common words in their name
            if not common_word:
                continue

            # match the song's main artist with the result's main artist
            main_artist_match = fuzz.ratio(
                slug_song_main_artist, slugify(result["artists_list"][0])
            )
            # print(f"? main_artist_match: {main_artist_match}")

            artist_match_number = main_artist_match
            if len(song.artists) > 1:
                # match the song's artists with the result's artists

                if len(song.artists) == len(result["artists_list"]):
                    artists_match = fuzz.ratio(slug_song_artists, slug_result_artists)
                    # print(f"exact artists_match: {artists_match}")
                else:
                    # Sort list1
                    artist1_list = list(map(slugify, song.artists))
                    artist1_list.sort()

                    # Sort list2
                    artist2_list = list(map(slugify, result["artists_list"]))
                    artist2_list.sort()

                    # Zip two sorted lists
                    zipped_lists = list(zip(song.artists, result["artists_list"]))

                    artist_match = 0.0
                    for artist1, artist2 in zipped_lists:
                        artist_match += fuzz.ratio(slugify(artist1), slugify(artist2))

                    artists_match = artist_match / len(zipped_lists)

                artist_match_number += artists_match

            artist_match = artist_match_number / (2 if len(song.artists) > 1 else 1)
            # print("? first artist_match: ", artist_match)

            # additional checks for results that are not songs
            if artist_match <= 50 and result["type"] != "song":
                # If we didn't find any artist match,
                # we fallback to channel name match
                channel_name_match = fuzz.ratio(
                    slugify(song.artist),
                    slug_result_artists,
                )

                if channel_name_match > artist_match_number:
                    artist_match = channel_name_match
                    # print("? second artist_match: ", artist_match)

                # If artist match is still too low,
                # we fallback to matching all song artist names
                # with the result's title
                if artist_match <= 50:
                    artist_title_match = 0
                    for artist in song.artists:
                        slug_artist = slugify(artist).replace("-", "")
                        if slug_artist in slug_result_name.replace("-", ""):
                            artist_title_match += 1

                    artist_title_match = (artist_title_match / len(song.artists)) * 100
                    # print(f"? artist_title_match: {artist_title_match}")

                    if artist_title_match > artist_match:
                        artist_match = artist_title_match
                        # print("? third artist_match: ", artist_match)

            # additional checks for results that are songs
            if artist_match < 70 and result["type"] == "song":
                # Check if the song name is very similar to the result name
                if (
                    fuzz.ratio(
                        slug_result_name,
                        slug_song_name,
                    )
                    >= 85
                ):
                    # If it is, we increase the artist match
                    artist_match += 10
                    # print("? song name artist_match: ", artist_match)

                    # if the result doesn't have the same number of artists but has
                    # the same main artist and similar name
                    # we add 30% to the artist match
                    if (
                        len(result["artists_list"]) < len(song.artists)
                        and slugify(result["artists_list"][0]) == slug_song_main_artist
                    ):
                        artist_match += 25
                        # print("? hacky artist_match: ", artist_match)

                # Check if the song album name is very similar to the result album name
                # if it is, we increase the artist match
                if slug_result_album:
                    if fuzz.ratio(slug_result_album, slug_song_album_name) >= 85:
                        artist_match += 10
                        # print("? album artist_match: ", artist_match)

                # Check if other song artists are in the result name
                # if they are, we increase the artist match
                # (main artist is already checked, so we skip it)
                for artist in song.artists[1:]:
                    slug_song_artist = slugify(artist)
                    if slug_song_artist in slug_result_name:
                        artist_match += 15 if len(song.artists[1:]) <= 2 else 10
                        # print("? other artist artist_match: ", artist_match)

            # print("? final artist_match: ", artist_match)

            # skip results with artist match lower than 70%
            if artist_match < 70:
                # print("! artist_match < 70 - skipping")
                continue

            # check if the artist match is higher than 100%
            # if it is, we set it to 100% (this shouldn't happen)
            artist_match = min(artist_match, 100)

            test_str1 = slug_result_name
            test_str2 = slug_song_name if result["type"] == "song" else slug_song_title

            # check if the artist is in the song name
            # but not in the result name
            # if it is, we add the artist to the result name
            for artist in song.artists:
                slug_song_artist = slugify(artist).replace("-", "")
                if slug_song_artist in test_str2.replace(
                    "-", ""
                ) and not slug_song_artist in test_str1.replace("-", ""):
                    test_str1 += f"-{slug_song_artist}"

            # same thing for for song name
            for artist in song.artists:
                slug_result_artist = slugify(artist).replace("-", "")
                if slug_result_artist in test_str1.replace(
                    "-", ""
                ) and not slug_result_artist in test_str2.replace("-", ""):
                    test_str2 += f"-{slug_result_artist}"

            test_str1 = test_str1.split("-")
            test_str2 = test_str2.split("-")

            test_str1.sort()
            test_str2.sort()

            test_str1 = "-".join(test_str1)
            test_str2 = "-".join(test_str2)

            # print(f"test_str1: {test_str1}")
            # print(f"test_str2: {test_str2}")

            # Calculate name match
            if artist_match >= 75:
                name_match = fuzz.ratio(
                    test_str1,
                    test_str2,
                )
            else:
                name_match = fuzz.ratio(
                    slug_result_name,
                    slug_song_name,
                )

            # Drop results with name match lower than 50%
            # print(f"name_match: {name_match}")
            if name_match < 50:
                # print("! name_match < 50 - skipping")
                continue

            # Find album match
            album_match = 0.0

            # Calculate album match only for songs
            if result["type"] == "song":
                if slug_result_album:
                    album_match = fuzz.ratio(slug_result_album, slug_song_album_name)

            # Calculate time match
            delta = result["duration"] - song.duration
            non_match_value = (delta**2) / song.duration * 100
            time_match = 100 - non_match_value

            # print(f"? time_match: {time_match}")

            # Calculate total match
            average_match = (artist_match + name_match) / 2

            # print(f"? album_match: {album_match}")
            # print(f"? time_match: {time_match}")
            # print(f"? average_match (only artist and name): {average_match}")

            if (
                result["type"] == "song"
                and slug_result_album
                and fuzz.partial_ratio(
                    slug_song_album_name, slug_result_name, score_cutoff=85
                )
            ):
                # If the result album name is similar to the song album name
                # and average match is higher than 80%
                # we add album match to the total match
                average_match = average_match + album_match / 2

                # print(f"? average_match with album_match: {average_match}")

            if time_match < 50 and average_match < 85:
                # If the time match is lower than 50% and the average match is lower than 85%
                # we skip the result
                # print("! time_match < 50 and average_match < 85 - skipping")
                continue

            if time_match < 50:
                # If the time match is lower than 50% but the average match is higher than 85%
                # we add time match to the average match

                # if the result is an isrc result we don't add time match
                if not is_isrc:
                    average_match = (average_match + time_match) / 2
                    # print(f"? average_match with time_match, not isrc: {average_match}")

            # print(f"? final average_match: {average_match}")

            # the results along with the avg Match
            links_with_match_value[result["link"]] = average_match

        return links_with_match_value
