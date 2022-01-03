from cursedspace import Panel


class KeyHelpPanel(Panel):
    def __init__(self, candidates, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.border = Panel.BORDER_ALL
        self.candidates = candidates
        self.padding = 5

    def autosize(self):
        height, width = self.app.size()
        # len(...)+2 is the space reserved for the borders
        self.resize(min(height-2, len(self.candidates)+2), width)
        self.move(height-self.dim[0]-1, 0)

    def paint(self):
        super().paint()
        if len(self.candidates) == 0:
            return

        column_widths = [max([len(line[column]) for line in self.candidates])
                         for column in range(len(self.candidates[0]))]
        # the last column stretches at most over the remaining length
        column_widths[-1] = (self.dim[1] - 2 - self.padding*(len(self.candidates[0])-1)) - sum(column_widths[:-1])
        for y, line in enumerate(sorted(self.candidates)):
            x = 1
            for column in range(len(column_widths)):
                if column_widths[column] <= 0 or x >= self.dim[1] - 2:
                    return
                self.win.addstr(y+1, x, line[column][:column_widths[column]])
                x += self.padding + column_widths[column]
        self.win.noutrefresh()

