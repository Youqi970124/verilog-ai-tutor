module top_module(input [31:0] a, input [31:0] b, output [31:0] sum);
  wire [15:0] low_sum, high_sum;
  wire low_cout, high_cout;
  add16 low_adder (.a(a[15:0]), .b(b[15:0]), .cin(1'b0), .sum(low_sum), .cout(low_cout));
  add16 high_adder (.a(a[31:16]), .b(b[31:16]), .cin(low_cout), .sum(high_sum), .cout(high_cout));
  assign sum = {high_sum, low_sum};
endmodule
