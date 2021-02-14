script = {
    "mappings": {

    },
    "scenes": [
        """
        user: ask_date
        bot: report_date
        user: ask_weather
        bot: report_weather:{"date": "2021-02-01"}
        """,
        """
        user: ask_weekday
        bot: report_weekday
        """
    ]
}