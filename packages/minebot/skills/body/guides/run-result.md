guide("run-result"): log, the return value, a thrown error, how values are converted.

log(...values)
  Adds one line to the run's logs. Each value that is a string is taken as it is; every
  other value is converted (below) and written with JSON.stringify. The parts are joined
  with one space and the line is cut to its first 2000 characters.
  The line leaves the body at once: lines logged before an error, a stop or a restart
  are in the report.
  The bridge keeps the lines per job; when a job has more than 400, the oldest 100 are
  dropped. A report holds the last 80.
  Returns undefined. It works while the run is paused and after it was told to stop.
  A line logged after the run has ended is added to that job's lines as long as the
  bridge still keeps the job.
  A routine called as skills.NAME(args) logs to the calling run's log; called as
  skills.NAME(args, fn), its `log` is fn.

The return value.
  When the function returns, the run ends with status 'done' and the report's `result`
  is the returned value, converted. `error` is None.

A thrown error.
  When the function throws, or returns a promise that rejects, the run ends with status
  'error' (the report's ended is "an error"), `result` is None, and `error` is the first
  6 lines of the error's stack; without a stack, of its message; without that, of the
  thrown value as a string. For an Error the first line is its name and message
  ("TypeError: x is not a function"), the next are the frames.
  Code that was told to stop and then throws, the error 'stopped' or another, ends with
  status 'stopped' and the error 'stopped' (guide("run-ending")).

How a value is converted.
  undefined                     null
  null, a number, a boolean     itself (NaN and Infinity arrive as null)
  a string                      itself; longer than 4000 characters: the first 4000 + '...'
  a bigint                      a number
  a function                    '[function]'
  an object or array more than 5 levels below the top value        '[deep]'
  a Vec3                        {x, y, z}, each rounded to 2 decimals
  an Error                      {error: its message}
  an array                      its first 200 elements, each converted
  an object with position, name and stateId (a Block)
                                {block: name, position}
  an object with position and type or username (an Entity)
                                {entity: name or username, kind: type, position, health}
  an object with count, name and slot (an Item)
                                {item: name, count, slot}
  any other object              its own enumerable keys, the first 61, each value converted
  a symbol                      its text
  The tests are made in this order; the first that holds decides. `position` in the three
  shapes is written as a Vec3 is: {x, y, z} with 2 decimals.
  A Map, a Set and a Date have no own enumerable keys: each becomes {}.
  An object that has itself inside it ends in '[deep]' at the sixth level.
  A Block, Entity or Item is reduced to the fields shown: no metadata, no nbt, no
  durability.

Values that cannot be read.
  A part x, y or z of a position that is not a finite number is given as null.
  When reading a return value throws (a getter of the value throws), the run ends with
  status 'done' and the result '[the value could not be read: MESSAGE]'. In log the
  error is thrown in the calling code.
