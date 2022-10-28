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
        """,
        """
        user: ask_date_weekday
        bot: report_date
        bot: report_weekday
        """,
        """
        user: hey
        bot: form{"name": "greet_form"}
        bot: form{"name": null}
        user: ask_weather
        bot: report_weather
        """,
        """
        user: hey
        bot: form{"name": "greet_form"}
        user: ask_weather
        bot: deactivate_form
        bot: report_weather
        """,
        """
        user: hey
        bot: form{"name": "greet_form"}
        user: ask_weekday
        bot: deactivate_form
        bot: report_weekday
        bot: form{"name": "greet_form"}
        bot: form{"name": null}
        """
    ],
    "rules": []
}