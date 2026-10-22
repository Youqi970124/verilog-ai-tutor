module top_module(input [31:0] a, input [31:0] b, input sub, output [31:0] sum);
  wire [31:0] b_xor;
  assign b_xor = b ^ {32{sub}};

  wire [15:0] sum_low, sum_high;
  wire carry_low;

  add16 low_adder (
    .a    (a[15:0]),
    .b    (b_xor[15:0]),
    .cin  (sub),
    .sum  (sum_low),
    .cout (carry_low)
  );

  add16 high_adder (
    .a    (a[31:16]),
    .b    (b_xor[31:16]),
    .cin  (carry_low),
    .sum  (sum_high),
    .cout ()
  );

  assign sum = {sum_high, sum_low};
endmodule
