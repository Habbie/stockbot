import re


class ColorHelper(object):

    @classmethod
    def white(cls, value):
        return "\x0300{}\x03".format(value)

    @classmethod
    def bold(cls, value):
        return "\x02{}\x02".format(value)

    @classmethod
    def red(cls, value):
        return "\x0304{}\x03".format(value)

    @classmethod
    def green(cls, value):
        return "\x0303{}\x03".format(value)

    @classmethod
    def grey(cls, value):
        return "\x0314{}\x03".format(value)

    @classmethod
    def yellow(cls, value):
        return "\x0308{}\x03".format(value)

    @classmethod
    def purple(cls, value):
        return "\x0306{}\x03".format(value)


def colorify(msg):
    return msg

def _colorify(msg):

    num_change_regex = re.compile("[^\w]?(total (percentage return|return)|%)[^\w]?", flags=re.IGNORECASE)
    num_important_change_regex = re.compile("[^\w]?(change|rebate percentage)[^\w]?", flags=re.IGNORECASE)
    num_recommendations_regex = re.compile("[^\w]?recommendations [^\w]?", flags=re.IGNORECASE)

    # split over pipe separated "groups"
    group_split = msg.split("|")
    group_rv = []

    for group in group_split:

        # split over comma separated "sections"
        section_split = group.split(",")

        section_rv = []

        for (index, section) in enumerate(section_split):

            # split over subject : value
            s_split = section.split(": ", 1)

            # there was no subject, just color everything grey
            if len(s_split) == 1:
                s_replace = ColorHelper.grey(s_split[0])

            # we identified subject : value
            else:
                (key, value) = s_split
                try:

                    # if value is a number
                    v = float(value)

                    # truncate decimals
                    v_s = "{:.3f}".format(v)

                    # check if number should be colored differently depending on positive or negative value
                    if num_change_regex.search(key) is not None:
                        # negative gets colored red
                        if v < 0:
                            value_replace = ColorHelper.red(v_s)

                        # positive gets colored green
                        else:
                            value_replace = ColorHelper.green(v_s)
                    elif num_important_change_regex.search(key) is not None:
                        # negative gets colored red and bold
                        if v < 0:
                            value_replace = ColorHelper.bold(ColorHelper.red(v_s))

                        # positive gets colored green and bold
                        else:
                            value_replace = ColorHelper.bold(ColorHelper.green(v_s))
                    else:
                        # unknown number gets colored grey
                        value_replace = ColorHelper.grey(v_s)

                except ValueError as e:

                    # first value should be white and highlighted
                    if index == 0:
                        value_replace = ColorHelper.bold(ColorHelper.white(value))
                    elif num_recommendations_regex.search(key) is not None:
                        # avanza recommendations in form of buy/hold/sell
                        r_split = value.split("/")
                        if len(r_split) == 3:
                            value_replace = r"{}/{}/{}".format(ColorHelper.green(r_split[0]),
                                                               ColorHelper.yellow(r_split[1]),
                                                               ColorHelper.red(r_split[2]))
                        else:
                            value_replace = ColorHelper.grey(value)
                    else:
                        # a non-number gets colored grey
                        value_replace = ColorHelper.grey(value)
                finally:
                    s_replace = r"{k}: {v}".format(k=ColorHelper.purple(key), v=value_replace)

            # append the result into a list
            section_rv.append(s_replace)

        # sew the list together into a string again
        group_rv.append(ColorHelper.white(",").join(section_rv))
    escaped_rv = " |".join(group_rv)
    return escaped_rv
